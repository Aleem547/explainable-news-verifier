"""Actual strict FastAPI request-model boundary; fixture imports, no HTTP or DB."""
import importlib
import sys
import types
import unittest
from unittest.mock import patch


class ReviewRequestBoundary(unittest.TestCase):
    def test_public_input_cannot_supply_operator_review_or_authority(self):
        from pydantic import ValidationError
        auth=types.ModuleType('apps.api.core.service_auth');auth.require_internal_verification=lambda:'google:fixture'
        db=types.ModuleType('apps.api.db.session');db.get_db_session=lambda:object()
        try:
            with patch.dict(sys.modules,{auth.__name__:auth,db.__name__:db}):
                route=importlib.import_module('apps.api.routes.article_verification')
                for key in ('external_trusted_origin_review','trusted_origin_review','reviewer_key','review_status',
                            'independent_corroboration_established','ORIGIN_REVIEW_STORE',
                            'external_reviewed_corroboration','favor_precision'):
                    with self.subTest(key=key),self.assertRaises(ValidationError):
                        route.ArticleVerificationRequest.model_validate({'kind':'pasted','text':'x'*120,key:True})
        finally:sys.modules.pop('apps.api.routes.article_verification',None)


if __name__=='__main__':unittest.main()
