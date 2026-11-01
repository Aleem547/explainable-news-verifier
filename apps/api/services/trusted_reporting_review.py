"""Authenticated operator assessments of exact reporting-origin pairs.

MAC verification authenticates an authorized local operator record, not the
publisher's facts. No review changes NLI admission or factual-truth flags.
The private trust directory is an OS-protected server configuration boundary.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
from urllib.parse import urlsplit
from uuid import UUID, uuid4

POLICY = 'trusted-reporting-origin-review-v1'
ENVIRONMENT_KEY = 'ORIGIN_REVIEW_STORE'
DECISIONS = frozenset({'INCONCLUSIVE', 'DEPENDENCY_DOCUMENTED', 'REVIEWED_DISTINCT_REPORTING'})
CHECKS = ('left_original_reporting', 'right_original_reporting', 'editorial_control',
          'syndication_and_wire', 'shared_primary_source')
MAX_FILE_BYTES = 262_144
SHA = re.compile(r'[a-f0-9]{64}\Z')
IDENTIFIER = re.compile(r'[A-Za-z0-9_.-]{3,80}\Z')
BINDING_FIELDS = ('passage_id', 'document_version_id', 'publisher_domain', 'article_url',
                  'parent_passage_id', 'input_sha256', 'input_start_offset',
                  'input_end_offset', 'snapshot_sha256', 'fetch_observation_id')


class TrustedReviewError(ValueError):
    pass


def require(value, code):
    if not value:
        raise TrustedReviewError(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def digest(value):
    return sha256(canonical(value).encode()).hexdigest()


def is_sha(value):
    return type(value) is str and SHA.fullmatch(value) is not None


def uuid_text(value):
    require(isinstance(value, (str, UUID)), 'invalid_review_identity')
    try:
        result = str(UUID(str(value)))
    except ValueError:
        raise TrustedReviewError('invalid_review_identity') from None
    require(str(value).lower() == result, 'noncanonical_review_identity')
    return result


def public_url(value):
    require(type(value) is str and 12 <= len(value) <= 2048
            and not any(c.isspace() or ord(c) < 32 for c in value)
            and '\\' not in value, 'invalid_review_reference_url')
    try:
        parsed = urlsplit(value)
        require(parsed.scheme == 'https' and parsed.hostname and '.' in parsed.hostname
                and parsed.port in (None, 443) and not parsed.username and not parsed.password
                and not parsed.fragment, 'invalid_review_reference_url')
        try:
            ipaddress.ip_address(parsed.hostname)
        except ValueError:
            pass
        else:
            raise TrustedReviewError('invalid_review_reference_url')
    except ValueError:
        raise TrustedReviewError('invalid_review_reference_url') from None
    return parsed


def evidence_binding(row):
    # Public server references already carry the exact audited paragraph identity.
    item = {k: str(getattr(row, k)) if isinstance(getattr(row, k), UUID)
            else getattr(row, k) for k in BINDING_FIELDS}
    for key in ('passage_id', 'document_version_id', 'parent_passage_id', 'fetch_observation_id'):
        item[key] = uuid_text(item[key])
    require(getattr(row, 'input_kind', None) == 'DERIVED_PARAGRAPH'
            and getattr(row, 'decisive_evidence_admitted', None) is True
            and getattr(row, 'nli_threshold_passed', None) is True
            and getattr(row, 'nli_label', None) in {'ENTAILMENT', 'CONTRADICTION'}
            and getattr(row, 'scope_exclusion_codes', ()) in ((), [])
            and item['passage_id'] != item['parent_passage_id'], 'ineligible_review_evidence')
    parsed = public_url(item['article_url'])
    require(type(item['publisher_domain']) is str and parsed.hostname == item['publisher_domain']
            and is_sha(item['snapshot_sha256']) and is_sha(item['input_sha256'])
            and type(item['input_start_offset']) is int and type(item['input_end_offset']) is int
            and 0 <= item['input_start_offset'] < item['input_end_offset'] <= 2_000_000,
            'invalid_review_evidence_binding')
    return item


def make_scope(claim, left, right, stance):
    require(type(claim) is str and 3 <= len(claim) <= 2000 and claim == claim.strip(), 'invalid_review_claim')
    label = {'SUPPORT_ONLY': 'ENTAILMENT', 'REFUTE_ONLY': 'CONTRADICTION'}.get(stance)
    require(label is not None and left.nli_label == right.nli_label == label, 'review_stance_mismatch')
    a, b = evidence_binding(left), evidence_binding(right)
    require(a['publisher_domain'] < b['publisher_domain']
            and a['document_version_id'] != b['document_version_id']
            and left.dependency_risk_family != right.dependency_risk_family
            and left.duplicate_group != right.duplicate_group, 'review_pair_not_distinct')
    return {'policy_version': POLICY, 'claim_sha256': sha256(claim.encode()).hexdigest(),
            'stance': stance, 'evidence': [a, b]}


@dataclass(frozen=True, slots=True)
class TrustedOriginPairReview:
    scope_sha256: str
    left_passage_id: str
    right_passage_id: str
    stance: str
    decision: str
    record_sha256: str | None = None
    reviewed_at: str | None = None
    expires_at: str | None = None


@dataclass(frozen=True, slots=True)
class TrustedOriginReviewSummary:
    status: str
    candidate_pair_count: int
    reviewed_pair_count: int
    distinct_reporting_pair_count: int
    inconclusive_pair_count: int
    dependency_documented_pair_count: int
    pending_pair_count: int
    unavailable_pair_count: int
    pairs: tuple[TrustedOriginPairReview, ...]
    policy_version: str = POLICY
    # Deliberately no 'independent_corroboration_established' or truth score.


def summary(pairs):
    decisions = [p.decision for p in pairs]
    distinct = decisions.count('REVIEWED_DISTINCT_REPORTING')
    inconclusive = decisions.count('INCONCLUSIVE')
    dependent = decisions.count('DEPENDENCY_DOCUMENTED')
    pending = decisions.count('PENDING')
    unavailable = decisions.count('REVIEW_UNAVAILABLE')
    if unavailable:
        status = 'REVIEW_UNAVAILABLE'
    elif dependent:
        status = 'DEPENDENCY_DOCUMENTED'
    elif distinct:
        status = 'REVIEWED_DISTINCT_REPORTING'
    elif inconclusive:
        status = 'INCONCLUSIVE'
    else:
        status = 'PENDING' if pairs else 'NO_ELIGIBLE_PAIR'
    return TrustedOriginReviewSummary(status, len(pairs), distinct + inconclusive + dependent,
                                     distinct, inconclusive, dependent, pending, unavailable, tuple(pairs))


def store_root(value):
    path = Path(value)
    require(path.is_absolute() and not path.is_symlink(), 'invalid_private_review_store')
    return path.resolve()


def read_private(path, *, maximum=MAX_FILE_BYTES):
    require(not path.is_symlink() and path.is_file(), 'private_review_file_unavailable')
    with path.open('rb') as handle:
        raw = handle.read(maximum + 1)
    require(0 < len(raw) <= maximum, 'private_review_file_size_invalid')
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'private_review_duplicate_json_key')
            result[key] = value
        return result
    def reject_constant(value):
        raise TrustedReviewError('private_review_nonfinite_json')
    try:
        return json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)
    except (ValueError, UnicodeError):
        raise TrustedReviewError('private_review_json_invalid') from None


def registry(root):
    require(root.is_dir() and not (root / 'records').is_symlink(), 'invalid_private_review_store')
    data = read_private(root / 'trust.json', maximum=1_048_576)
    require(type(data) is dict and set(data) == {'policy_version', 'reviewers', 'revoked_records', 'superseded_records'}
            and data['policy_version'] == POLICY and type(data['reviewers']) is dict
            and 1 <= len(data['reviewers']) <= 32, 'private_review_registry_invalid')
    for key_id, reviewer in data['reviewers'].items():
        require(type(key_id) is str and IDENTIFIER.fullmatch(key_id)
                and type(reviewer) is dict and set(reviewer) == {'label', 'secret_hex', 'active'}
                and type(reviewer['label']) is str and IDENTIFIER.fullmatch(reviewer['label'])
                and is_sha(reviewer['secret_hex']) and type(reviewer['active']) is bool,
                'private_review_registry_invalid')
    for key in ('revoked_records', 'superseded_records'):
        require(type(data[key]) is list and len(data[key]) <= 10_000
                and len(set(data[key])) == len(data[key]), 'private_review_registry_invalid')
        for identity in data[key]:
            uuid_text(identity)
    return data


def timestamp(value):
    require(type(value) is str and len(value) <= 64, 'invalid_review_timestamp')
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        raise TrustedReviewError('invalid_review_timestamp') from None
    require(result.tzinfo is not None and result.utcoffset() is not None, 'invalid_review_timestamp')
    return result


def validate_checks(checks, decision):
    require(type(checks) is dict and set(checks) <= set(CHECKS), 'invalid_review_checks')
    if decision == 'REVIEWED_DISTINCT_REPORTING':
        require(set(checks) == set(CHECKS), 'distinct_reporting_review_evidence_required')
    if decision == 'DEPENDENCY_DOCUMENTED':
        require(bool(checks), 'documented_dependency_evidence_required')
    for section in checks.values():
        require(type(section) is dict and set(section) == {'explanation', 'references'}
                and type(section['explanation']) is str and 20 <= len(section['explanation']) <= 2000
                and type(section['references']) is list and 1 <= len(section['references']) <= 5,
                'invalid_review_check')
        for reference in section['references']:
            require(type(reference) is dict and set(reference) == {'url', 'sha256'}
                    and is_sha(reference['sha256']), 'invalid_review_reference')
            public_url(reference['url'])


def verify_envelope(envelope, scope, trust, now):
    require(type(envelope) is dict and set(envelope) == {'payload', 'mac_sha256'}
            and type(envelope['payload']) is dict and is_sha(envelope['mac_sha256']), 'review_record_invalid')
    payload = envelope['payload']
    require(set(payload) == {'policy_version', 'record_id', 'key_id', 'scope', 'scope_sha256',
                            'decision', 'issued_at', 'expires_at', 'reason', 'checks'}
            and payload['policy_version'] == POLICY and payload['scope'] == scope
            and payload['scope_sha256'] == digest(scope), 'review_record_scope_mismatch')
    identity = uuid_text(payload['record_id'])
    require(identity not in trust['revoked_records'] and identity not in trust['superseded_records'],
            'review_record_revoked_or_superseded')
    reviewer = trust['reviewers'].get(payload['key_id'])
    require(reviewer is not None and reviewer['active'] is True, 'reviewer_not_authorized')
    expected = hmac.digest(bytes.fromhex(reviewer['secret_hex']), canonical(payload).encode(), 'sha256').hex()
    require(hmac.compare_digest(expected, envelope['mac_sha256']), 'review_record_mac_invalid')
    issued, expires = timestamp(payload['issued_at']), timestamp(payload['expires_at'])
    require(issued <= now + timedelta(minutes=5) and issued < expires and now < expires
            and expires - issued <= timedelta(days=30), 'review_record_expired_or_future')
    require(type(payload['decision']) is str and payload['decision'] in DECISIONS
            and type(payload['reason']) is str and 20 <= len(payload['reason']) <= 2000,
            'review_record_decision_invalid')
    validate_checks(payload['checks'], payload['decision'])
    return payload


def resolve_pair_scopes(claim, refs, pair_ids, *, store, now=None):
    now = now if now is not None else datetime.now(UTC)
    by_id = {str(r.passage_id): r for r in refs}
    require(len(by_id) == len(refs) and len(pair_ids) <= 190, 'invalid_review_reference_set')
    scopes = []
    for left, right, stance in pair_ids:
        require(left in by_id and right in by_id, 'review_pair_not_in_evidence')
        scope = make_scope(claim, by_id[left], by_id[right], stance)
        scopes.append((left, right, stance, scope))
    require(len({digest(s) for _, _, _, s in scopes}) == len(scopes), 'duplicate_review_pair')
    try:
        root = store_root(store)
        trust = registry(root)
        trust_digest = digest(trust)
    except (OSError, ValueError, TypeError, KeyError):
        return summary(tuple(TrustedOriginPairReview(digest(s), a, b, stance, 'REVIEW_UNAVAILABLE')
                             for a, b, stance, s in scopes))
    results = []
    for left, right, stance, scope in scopes:
        base = dict(scope_sha256=digest(scope), left_passage_id=left, right_passage_id=right, stance=stance)
        path = root / 'records' / (digest(scope) + '.json')
        if not path.exists() and not path.is_symlink():
            results.append(TrustedOriginPairReview(**base, decision='PENDING'))
            continue
        try:
            envelope = read_private(path)
            payload = verify_envelope(envelope, scope, trust, now)
            results.append(TrustedOriginPairReview(**base, decision=payload['decision'],
                record_sha256=digest(envelope), reviewed_at=payload['issued_at'], expires_at=payload['expires_at']))
        except (OSError, ValueError, TypeError, KeyError):
            results.append(TrustedOriginPairReview(**base, decision='REVIEW_UNAVAILABLE'))
    # A concurrent revocation/registry edit cannot leave an earlier approval valid.
    try:
        require(digest(registry(root)) == trust_digest, 'review_registry_changed_during_read')
    except (OSError, ValueError, TypeError, KeyError):
        return summary(tuple(TrustedOriginPairReview(digest(s), a, b, stance, 'REVIEW_UNAVAILABLE')
                             for a, b, stance, s in scopes))
    return summary(tuple(results))


def resolve_trusted_origin_review(claim, refs, candidates):
    store = os.environ.get(ENVIRONMENT_KEY)
    if not store:
        return None
    pairs = tuple((str(c.left_passage_id), str(c.right_passage_id), c.stance) for c in candidates)
    return resolve_pair_scopes(claim, refs, pairs, store=store)


def validate_trusted_origin_review(value, *, claim, refs, candidate_count):
    require(type(value) is TrustedOriginReviewSummary and value.policy_version == POLICY
            and type(value.pairs) is tuple and value.candidate_pair_count == candidate_count
            and len(value.pairs) == candidate_count
            and all(type(p) is TrustedOriginPairReview for p in value.pairs), 'invalid_trusted_review_summary')
    counts = (value.candidate_pair_count, value.reviewed_pair_count, value.distinct_reporting_pair_count,
              value.inconclusive_pair_count, value.dependency_documented_pair_count,
              value.pending_pair_count, value.unavailable_pair_count)
    require(type(candidate_count) is int and 0 <= candidate_count <= 190
            and all(type(n) is int and 0 <= n <= 190 for n in counts), 'invalid_trusted_review_counts')
    store = os.environ.get(ENVIRONMENT_KEY)
    require(bool(store), 'trusted_review_store_not_configured')
    pairs = tuple((p.left_passage_id, p.right_passage_id, p.stance) for p in value.pairs)
    fresh = resolve_pair_scopes(claim, refs, pairs, store=store)
    require(value == fresh, 'trusted_review_summary_replay_mismatch')


def atomic_private(path, value, *, exclusive=False):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(not path.parent.is_symlink() and not path.is_symlink(), 'private_review_symlink_refused')
    if exclusive:
        with path.open('x', encoding='utf-8') as handle:
            handle.write(canonical(value) + '\n')
        path.chmod(0o600)
        return
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as handle:
            handle.write(canonical(value) + '\n')
        temporary.chmod(0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def locked_store(root):
    lock = root / 'operator-write.lock'
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise TrustedReviewError('review_store_locked') from None
    try:
        os.close(descriptor)
        yield
    finally:
        lock.unlink(missing_ok=True)


def init_store(path, reviewer_label):
    require(type(reviewer_label) is str and IDENTIFIER.fullmatch(reviewer_label), 'invalid_reviewer_label')
    root = store_root(path)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with locked_store(root):
        require(not (root / 'trust.json').exists(), 'review_store_already_initialized')
        (root / 'records').mkdir(mode=0o700, exist_ok=True)
        (root / 'history').mkdir(mode=0o700, exist_ok=True)
        key_id = 'operator-' + uuid4().hex
        atomic_private(root / 'trust.json', {'policy_version': POLICY,
            'reviewers': {key_id: {'label': reviewer_label, 'secret_hex': secrets.token_hex(32), 'active': True}},
            'revoked_records': [], 'superseded_records': []}, exclusive=True)
    return key_id


def sign_review(path, draft, key_id, *, confirm_distinct=False, valid_days=7, now=None):
    root = store_root(path)
    require(type(valid_days) is int and 1 <= valid_days <= 30, 'invalid_review_validity')
    require(type(draft) is dict and set(draft) == {'scope', 'decision', 'reason', 'checks'}, 'invalid_review_draft')
    require(draft['decision'] in DECISIONS
            and (draft['decision'] != 'REVIEWED_DISTINCT_REPORTING' or confirm_distinct is True),
            'explicit_distinct_reporting_review_confirmation_required')
    with locked_store(root):
        trust = registry(root)
        reviewer = trust['reviewers'].get(key_id)
        require(reviewer is not None and reviewer['active'] is True, 'reviewer_not_authorized')
        at = now if now is not None else datetime.now(UTC)
        payload = {'policy_version': POLICY, 'record_id': str(uuid4()), 'key_id': key_id,
            'scope': draft['scope'], 'scope_sha256': digest(draft['scope']),
            'decision': draft['decision'], 'issued_at': at.isoformat(),
            'expires_at': (at + timedelta(days=valid_days)).isoformat(),
            'reason': draft['reason'], 'checks': draft['checks']}
        envelope = {'payload': payload, 'mac_sha256': hmac.digest(bytes.fromhex(reviewer['secret_hex']),
                    canonical(payload).encode(), 'sha256').hex()}
        # Validation of the scope itself is repeated against real evidence on read.
        verify_envelope(envelope, draft['scope'], trust, at)
        record_file = root / 'records' / (payload['scope_sha256'] + '.json')
        if record_file.exists():
            prior = read_private(record_file)
            prior_id = uuid_text(prior['payload']['record_id'])
            if prior_id not in trust['superseded_records']:
                trust['superseded_records'].append(prior_id)
            require(len(trust['superseded_records']) <= 10_000, 'review_history_limit_reached')
        # Invalidate a replaced record before changing its active pointer.
        atomic_private(root / 'trust.json', trust)
        atomic_private(root / 'history' / (payload['record_id'] + '.json'), envelope, exclusive=True)
        atomic_private(record_file, envelope)
    return {'record_id': payload['record_id'], 'scope_sha256': payload['scope_sha256'],
            'record_sha256': digest(envelope), 'decision': payload['decision']}


def revoke_review(path, *, record_id=None, key_id=None):
    root = store_root(path)
    require((record_id is None) != (key_id is None), 'one_revocation_target_required')
    with locked_store(root):
        trust = registry(root)
        if record_id is not None:
            identity = uuid_text(record_id)
            if identity not in trust['revoked_records']:
                trust['revoked_records'].append(identity)
            require(len(trust['revoked_records']) <= 10_000, 'review_revocation_limit_reached')
        else:
            require(key_id in trust['reviewers'], 'reviewer_not_authorized')
            trust['reviewers'][key_id]['active'] = False
        atomic_private(root / 'trust.json', trust)
