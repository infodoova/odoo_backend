# doova_one_view/tests/test_e2e_contracts.py

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

import unittest
from doova_one_view.api.agent.routes import ChatRequest, extract_context_ids

class TestE2EContracts(unittest.TestCase):

    def test_chat_request_field_alias_normalization(self):
        """Verify ChatRequest handles frontend payload aliases (text, userInput, query, sessionId, tenantId, companyId)."""
        # Alias variation 1: frontend sending text + sessionId + tenantId
        payload1 = {
            "text": "What is our Q1 revenue?",
            "sessionId": "sess_12345",
            "tenantId": "tenant_abc",
            "companyId": 1
        }
        req1 = ChatRequest(**payload1)
        self.assertEqual(req1.query, "What is our Q1 revenue?")
        self.assertEqual(req1.session_id, "sess_12345")
        self.assertEqual(req1.tenant_id, "tenant_abc")
        self.assertEqual(req1.company_id, 1)

        # Alias variation 2: frontend sending userInput + query + companyIds
        payload2 = {
            "userInput": "Show inventory alerts",
            "query": "Show inventory alerts",
            "companyIds": [1, 2, 3]
        }
        req2 = ChatRequest(**payload2)
        self.assertEqual(req2.content, "Show inventory alerts")
        self.assertEqual(req2.company_ids, [1, 2, 3])

    def test_extract_context_ids_dict_and_model(self):
        """Verify extract_context_ids extracts primary and list IDs for tenants and companies."""
        valid_uuid = "3fa85f64-5717-4562-b3fc-2c963f66afa6"
        req = ChatRequest(
            tenantId=valid_uuid,
            companyIds=[10, 20]
        )
        primary_tenant, tenant_ids, primary_company, company_ids = extract_context_ids(req)
        
        self.assertEqual(primary_tenant, valid_uuid)
        self.assertEqual(tenant_ids, [valid_uuid])
        self.assertIsNone(primary_company)  # multiple company IDs, primary is None
        self.assertEqual(company_ids, [10, 20])

    def test_extract_context_ids_single_company(self):
        """Verify single company ID resolves to primary_company_id."""
        req = ChatRequest(companyId=42)
        primary_tenant, tenant_ids, primary_company, company_ids = extract_context_ids(req)
        self.assertEqual(primary_company, 42)
        self.assertEqual(company_ids, [42])

    def test_extract_context_ids_raw_dict(self):
        """Verify raw dictionary payload processing in extract_context_ids."""
        uuid1 = "3fa85f64-5717-4562-b3fc-2c963f66afa6"
        uuid2 = "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d"
        raw_dict = {
            "tenant_ids": [uuid1, uuid2],
            "companyId": 5
        }
        primary_tenant, tenant_ids, primary_company, company_ids = extract_context_ids(raw_dict)
        self.assertEqual(primary_tenant, uuid1)
        self.assertEqual(tenant_ids, [uuid1, uuid2])
        self.assertEqual(primary_company, 5)
        self.assertEqual(company_ids, [5])

if __name__ == "__main__":
    unittest.main()
