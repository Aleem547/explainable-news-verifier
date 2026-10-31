"""Local operator tool. Reviewer secrets never enter a public request or report."""
import argparse
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from apps.api.services.trusted_reporting_review import (
    CHECKS, TrustedReviewError, digest, init_store, make_scope,
    read_private, registry, require, revoke_review, sign_review, store_root,
)


def load_article(path):
    require(path.stat().st_size <= 5_000_000, 'report_file_too_large')
    if path.suffix.lower()=='.zip':
        with ZipFile(path) as zipped:
            info=zipped.getinfo('integration_report.json')
            require(info.file_size <= 2_000_000, 'report_file_too_large')
            data=json.loads(zipped.read(info))
    else:
        data=json.loads(path.read_text(encoding='utf-8-sig'))
    if 'api_observations' in data:
        choices=[x['article_report'] for x in data['api_observations']
                 if x.get('real_backend_sample_conditions_passed') is True and not x.get('control_request')]
        require(len(choices)==1, 'one_completed_public_sample_required')
        data=choices[0]
    require(type(data) is dict and type(data.get('claims')) is list, 'article_report_required')
    return data


def write_template(report, output, pair_index):
    article=load_article(report)
    choices=[]
    for claim in article['claims']:
        review=claim.get('external_trusted_origin_review')
        if not review:
            continue
        refs={r['passage_id']:SimpleNamespace(**r) for r in claim['external_references']}
        for pair in review['pairs']:
            scope=make_scope(claim['literal_text'],refs[pair['left_passage_id']],
                             refs[pair['right_passage_id']],pair['stance'])
            require(digest(scope)==pair['scope_sha256'], 'public_review_scope_mismatch')
            choices.append(scope)
    require(type(pair_index) is int and 0 <= pair_index < len(choices),
            'eligible_pair_with_server_review_scope_required')
    draft={'scope':choices[pair_index],'decision':'INCONCLUSIVE',
           'reason':'Original reporting evidence has not yet been established for both selected inputs.',
           'checks':{}}
    with output.open('x',encoding='utf-8') as handle:
        handle.write(json.dumps(draft,indent=2)+'\n')
    return {'status':'REVIEW_DRAFT_CREATED','file':str(output),
            'scope_sha256':digest(draft['scope']),'default_decision':'INCONCLUSIVE',
            'required_distinct_reporting_sections':list(CHECKS)}


def outside_project(path):
    root=store_root(path)
    require(not root.is_relative_to(ROOT)
            and not any((p/'.git').exists() for p in (root,*root.parents)),
            'private_review_store_must_be_outside_git_project')
    return root


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    setup=commands.add_parser('init');setup.add_argument('--store',type=Path,required=True)
    setup.add_argument('--reviewer-label',required=True)
    template=commands.add_parser('template');template.add_argument('--report',type=Path,required=True)
    template.add_argument('--out',type=Path,required=True);template.add_argument('--pair-index',type=int,default=0)
    sign=commands.add_parser('sign');sign.add_argument('--store',type=Path,required=True)
    sign.add_argument('--draft',type=Path,required=True);sign.add_argument('--key-id',required=True)
    sign.add_argument('--valid-days',type=int,default=7)
    sign.add_argument('--confirm-distinct-reporting-review',action='store_true')
    revoke=commands.add_parser('revoke');revoke.add_argument('--store',type=Path,required=True)
    targets=revoke.add_mutually_exclusive_group(required=True)
    targets.add_argument('--record-id');targets.add_argument('--key-id')
    listing=commands.add_parser('reviewers');listing.add_argument('--store',type=Path,required=True)
    args=parser.parse_args()
    if args.command=='init':
        key=init_store(outside_project(args.store),args.reviewer_label)
        return {'status':'PRIVATE_REVIEW_STORE_CREATED','key_id':key,
                'server_environment_variable':'ORIGIN_REVIEW_STORE',
                'environment_file_modified':False,'secrets_exported':False}
    if args.command=='template':return write_template(args.report,args.out,args.pair_index)
    root=outside_project(args.store)
    if args.command=='sign':
        result=sign_review(root,read_private(args.draft),args.key_id,
                           valid_days=args.valid_days,confirm_distinct=args.confirm_distinct_reporting_review)
        return {'status':'OPERATOR_REVIEW_SIGNED',**result,'factual_verification_claimed':False}
    if args.command=='revoke':
        revoke_review(root,record_id=args.record_id,key_id=args.key_id)
        return {'status':'OPERATOR_REVIEW_REVOKED'}
    trust=registry(root)
    return {'reviewers':[{'key_id':key,'label':r['label'],'active':r['active']}
                         for key,r in trust['reviewers'].items()]}


if __name__=='__main__':
    try:print(json.dumps(main(),indent=2))
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({'status':'STOPPED','error_type':type(error).__name__,
                          'code':str(error) if type(error) is TrustedReviewError else 'operator_input_unavailable'}))
        raise SystemExit(1)
