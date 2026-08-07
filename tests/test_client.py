"""Tests for Schwab Advisor client."""

from unittest.mock import MagicMock, patch

import pytest
from schwab_advisor import __version__
from schwab_advisor.client import SchwabAdvisorClient, product_not_attached
import httpx

from schwab_advisor.models import (
    AccountHoldersResponse,
    AccountOwnerListResponse,
    AccountProfilesResponse,
    AccountRmdResponse,
    AccountRolesResponse,
    AccountsResponse,
    AccountSyncResponse,
    AddressChangeCreateResponse,
    AddressChangesResponse,
    AlertArchiveResponse,
    AlertDetailResponse,
    AlertsResponse,
    AlertUpdateResponse,
    BalanceDetailResponse,
    BalanceListResponse,
    DataDeliveryEnrollmentResponse,
    MoveMoneyActivitiesResponse,
    MoveMoneyActivity,
    MasterAccountsResponse,
    OrdersResponse,
    OrdersStatusResponse,
    PositionDetailResponse,
    PositionListResponse,
    ProfilesListResponse,
    ReportsResponse,
    PreferencesAndAuthorizationsResponse,
    ServiceRequestCreateResponse,
    ServiceRequestTopicsResponse,
    StatusEventsPostResponse,
    StatusEventsResponse,
    StatusFeedCreateResponse,
    StandingInstruction,
    StandingInstructionDetail,
    StandingInstructionsResponse,
    StatusFeedResponse,
    TransactionDetail,
    TransactionsResponse,
    UserAuthorizationsResponse,
)


def test_version():
    assert __version__ == "0.4.1"


def test_client_defaults_to_env_auth():
    """Client defaults to SchwabAuth.from_env() when no auth provided."""
    with patch.dict("os.environ", {"SCHWAB_TOKEN_FILE": "/tmp/test_tokens.json"}, clear=False):
        client = SchwabAdvisorClient()
        assert client.auth is not None
        assert client.environment == "sandbox"


def test_client_inherits_environment_from_auth():
    """Client infers environment from auth object."""
    from schwab_advisor.auth import SchwabAuth
    auth = SchwabAuth(
        client_id="id", client_secret="secret",
        redirect_uri="https://example.com", environment="production",
    )
    client = SchwabAdvisorClient(auth=auth)
    assert client.environment == "production"


def test_client_access_token_only_defaults_sandbox():
    """Client with only access_token defaults to sandbox environment."""
    client = SchwabAdvisorClient(access_token="test_token")
    assert client.environment == "sandbox"
    assert client.auth is None


def test_client_with_access_token():
    """Client can be created with direct access token."""
    client = SchwabAdvisorClient(access_token="test_token")
    assert client._access_token == "test_token"
    assert client._base_url("bulk") == "https://sandbox.schwabapi.com/as-integration/bulk/v2"
    assert client._base_url("accounts") == "https://sandbox.schwabapi.com/as-integration/accounts/v2"


def test_client_with_production_environment():
    """Client uses production URL when specified."""
    client = SchwabAdvisorClient(access_token="test_token", environment="production")
    assert client._base_url("bulk") == "https://api.schwabapi.com/as-integration/bulk/v2"
    assert client._base_url("accounts") == "https://api.schwabapi.com/as-integration/accounts/v2"


def test_client_with_custom_base_url():
    """Client accepts custom base URL (overrides segment routing)."""
    client = SchwabAdvisorClient(
        access_token="test_token", base_url="https://custom.example.com"
    )
    assert client._base_url("bulk") == "https://custom.example.com"
    assert client._base_url("accounts") == "https://custom.example.com"


def test_client_headers_no_body():
    """GET requests should not include Content-Type."""
    client = SchwabAdvisorClient(access_token="test_token", resource_version=2)
    headers = client._get_headers(has_body=False)
    assert headers["Authorization"] == "Bearer test_token"
    assert headers["Accept"] == "application/vnd.api+json"
    assert headers["Schwab-Resource-Version"] == "2"
    assert "Content-Type" not in headers


def test_client_headers_with_body():
    """POST requests should include Content-Type."""
    client = SchwabAdvisorClient(access_token="test_token")
    headers = client._get_headers(has_body=True)
    assert headers["Content-Type"] == "application/json"


def test_client_correlation_id_unique():
    """Each request gets a unique correlation ID."""
    client = SchwabAdvisorClient(access_token="test_token")
    headers1 = client._get_headers()
    headers2 = client._get_headers()
    assert headers1["Schwab-Client-CorrelId"] != headers2["Schwab-Client-CorrelId"]


def _mock_response(json_data, status_code=200):
    """Create a mock httpx response."""
    mock = MagicMock()
    mock.json.return_value = json_data
    mock.status_code = status_code
    mock.raise_for_status.return_value = None
    return mock


def _setup_mock_client(mock_client_cls, json_data, status_code=200):
    """Configure a mock httpx.Client class to return a mock response."""
    mock_instance = MagicMock()
    mock_instance.request.return_value = _mock_response(json_data, status_code)
    mock_client_cls.return_value = mock_instance
    return mock_instance


def _error_response(status_code, www_authenticate="", text=""):
    """Mock response whose raise_for_status raises HTTPStatusError.

    www_authenticate is where Apigee puts the product-not-attached
    marker (InvalidAPICallAsNoApiProductMatchFound) — it never appears
    in the body."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.headers = {"www-authenticate": www_authenticate} if www_authenticate else {}
    mock.text = text
    mock.json.return_value = {}
    mock.raise_for_status.side_effect = httpx.HTTPStatusError(
        f"HTTP {status_code}", request=MagicMock(), response=mock,
    )
    return mock


# --- Alerts ---


class TestAlerts:
    @patch("schwab_advisor.client.httpx.Client")
    def test_get_alerts(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": [
                {"id": 15157510, "type": "alert", "attributes": {
                    "formattedMasterAccount": "8174295",
                    "type": "User Alert", "status": "New",
                }},
            ],
            "meta": {"paging": {"nextCursor": "3"}, "count": {"actual": 1, "total": 825}},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_alerts(page_limit=5)
        assert isinstance(resp, AlertsResponse)
        assert len(resp.alerts) == 1
        assert resp.alerts[0].id == 15157510
        assert resp.alerts[0].alert_type == "User Alert"
        assert resp.next_cursor == "3"
        # Verify it uses accounts segment
        url = mock_inst.request.call_args[1].get("url", mock_inst.request.call_args[0][1])
        assert "/accounts/v2/alerts" in url

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_alerts_with_filters(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {"data": [], "meta": {}})
        client = SchwabAdvisorClient(access_token="test_token")
        client.get_alerts(
            filter_types=["UserAlert", "Trading"],
            sort_by="CreatedDate",
            sort_direction="Desc",
            show_account="Show",
        )
        params = mock_inst.request.call_args[1]["params"]
        assert params["filter[types]"] == "UserAlert, Trading"
        assert params["sortBy"] == "CreatedDate"
        assert params["showAccount"] == "Show"

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_alert_detail(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": {"id": 15157510, "type": "alert-detail", "attributes": {
                "type": "User Alert", "detailText": "<html>...</html>",
                "statusHistory": [{"status": "New"}],
            }},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_alert_detail(15157510, master_account="8174295")
        assert isinstance(resp, AlertDetailResponse)
        assert resp.alert.id == 15157510
        # Verify Schwab-Client-Ids header
        headers = mock_inst.request.call_args[1]["headers"]
        assert headers["Schwab-Client-Ids"] == "masterAccount=8174295"

    @patch("schwab_advisor.client.httpx.Client")
    def test_archive_alerts(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": {"id": "uuid", "type": "alerts-archive", "attributes": {
                "areAllArchived": True,
                "archiveDetails": [
                    {"alertId": 15157526, "hasArchivedStatusChanged": True,
                     "noArchivedStatusChangeReason": ""},
                ],
            }},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.archive_alerts([15157526])
        assert isinstance(resp, AlertArchiveResponse)
        assert resp.are_all_archived is True
        assert resp.archive_details[0].alert_id == 15157526
        # Verify flat body (not JSON:API)
        body = mock_inst.request.call_args[1]["json"]
        assert body == {"alertIds": [15157526]}

    @patch("schwab_advisor.client.httpx.Client")
    def test_update_alert_204(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {}, status_code=204)
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.update_alert(15157510, "Unarchive")
        assert isinstance(resp, AlertUpdateResponse)
        assert resp.id == "15157510"
        assert resp.raw_data is None
        # Body must be flat {"action": "..."} per official docs
        body = mock_inst.request.call_args[1]["json"]
        assert body == {"action": "Unarchive"}


# --- Service Requests ---


class TestServiceRequests:
    @patch("schwab_advisor.client.httpx.Client")
    def test_get_topics(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": [
                {"id": "55df8198", "type": "service-request-topic", "attributes": {
                    "name": "Open New Account", "order": 1,
                    "subTopics": [
                        {"name": "Brokerage", "isAttachmentAllowed": True,
                         "isAttachmentRequired": True, "maxAttachmentSize": 30},
                    ],
                }},
            ],
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_service_request_topics()
        assert isinstance(resp, ServiceRequestTopicsResponse)
        assert len(resp.topics) == 1
        assert resp.topics[0].name == "Open New Account"
        assert resp.topics[0].sub_topics[0].name == "Brokerage"

    @patch("schwab_advisor.client.httpx.Client")
    def test_create_service_request(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": {"id": "SR378912733804863", "type": "service-request",
                     "attributes": {
                         "topicName": "Money Movement",
                         "subTopicName": "Other",
                         "description": "Test",
                         "creator": "test_user",
                     }},
        }, status_code=201)
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.create_service_request(
            topic_name="Money Movement",
            sub_topic_name="Other",
            description="Test",
            master_account="8174295",
        )
        assert isinstance(resp, ServiceRequestCreateResponse)
        assert resp.id == "SR378912733804863"
        body = mock_inst.request.call_args[1]["json"]
        assert body["topicName"] == "Money Movement"
        assert body["masterAccount"] == "8174295"


# --- Status ---


class TestStatus:
    @patch("schwab_advisor.client.httpx.Client")
    def test_create_status_feed(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": {"id": "feed-uuid", "type": "status-feed", "attributes": {
                "statusObjects": [
                    {"statusObjectId": "obj-1", "category": "Envelope",
                     "title": "Test", "statusEvents": []},
                ],
            }},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.create_status_feed(status=["New"])
        assert isinstance(resp, StatusFeedCreateResponse)
        assert resp.feed_id == "feed-uuid"
        assert len(resp.status_objects) == 1
        # Verify body format — PascalCase top-level keys (verified accepted
        # in both sandbox and production as of 2026-05).
        body = mock_inst.request.call_args[1]["json"]
        assert body["Status"] == ["New"]
        assert body["ShowAccount"] == "Mask"

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_status_feed(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": [
                {"id": "obj-1", "type": "status-object", "attributes": {
                    "category": "Digital Envelope", "title": "AC Open",
                    "formattedMasterAccount": "***4295",
                    "statusEvents": [
                        {"id": "evt-1", "type": "status-event",
                         "attributes": {"status": "New"}},
                    ],
                }},
            ],
            "meta": {"paging": {}, "count": {"actual": 1}},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_status_feed("feed-uuid")
        assert isinstance(resp, StatusFeedResponse)
        assert len(resp.status_objects) == 1
        assert resp.status_objects[0].category == "Digital Envelope"
        assert len(resp.status_objects[0].status_events) == 1

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_status_events(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": [
                {"id": "evt-1", "type": "status-event", "attributes": {
                    "statusObjectId": "obj-1", "status": "New",
                    "currentStatus": "Draft", "assignmentGroup": "Advisor",
                }},
            ],
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_status_events("feed-1", "obj-1")
        assert isinstance(resp, StatusEventsResponse)
        assert len(resp.events) == 1
        assert resp.events[0].status == "New"
        assert resp.events[0].assignment_group == "Advisor"
        # Verify URL
        url = mock_inst.request.call_args[1].get("url", mock_inst.request.call_args[0][1])
        assert "status-feed/feed-1/status-objects/obj-1/status-events" in url

    @patch("schwab_advisor.client.httpx.Client")
    def test_post_status_events(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {"data": {"id": "batch-1"}})
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.post_status_events(
            myq_case_id="CASE123",
            master_account="8174295",
            message="Test event",
        )
        assert isinstance(resp, StatusEventsPostResponse)
        body = mock_inst.request.call_args[1]["json"]
        assert body["myqCaseId"] == "CASE123"
        assert body["masterAccount"] == "8174295"
        assert body["message"] == "Test event"


# --- AS Account (bulk segment) ---


class TestAccountProfiles:
    @patch("schwab_advisor.client.httpx.Client")
    def test_get_account_profiles(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": [{"attributes": {
                "formattedAccount": "1234-5678",
                "formattedMasterAccount": "MASTER-1",
                "accountRegistrationType": "Individual",
            }}],
            "meta": {"paging": {"nextCursor": "2"}, "count": {"actual": 1}},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_account_profiles(page_limit=10, show_account="Show")
        assert isinstance(resp, AccountProfilesResponse)
        assert len(resp.profiles) == 1
        assert resp.profiles[0].formatted_account == "1234-5678"
        assert resp.next_cursor == "2"
        # Verify bulk segment
        call_kwargs = mock_inst.request.call_args
        url = call_kwargs.kwargs.get("url", call_kwargs.args[1] if len(call_kwargs.args) > 1 else "")
        assert "/bulk/v2/account-profiles" in url
        params = mock_inst.request.call_args[1]["params"]
        assert params["showAccount"] == "Show"

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_account_profiles_with_total_count(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": [],
            "meta": {"paging": {}, "count": {"actual": 0}},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        client.get_account_profiles(include_total_count=True)
        params = mock_inst.request.call_args[1]["params"]
        assert params["includeTotalCount"] == "true"

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_all_account_profiles_pagination(self, mock_client_cls):
        """Tests the pagination loop accumulates results and terminates."""
        mock_inst = MagicMock()
        mock_client_cls.return_value = mock_inst
        mock_inst.request.side_effect = [
            _mock_response({
                "data": [{"attributes": {"formattedAccount": "1111"}}],
                "meta": {"paging": {"nextCursor": "page2"}, "count": {"actual": 1}},
            }),
            _mock_response({
                "data": [{"attributes": {"formattedAccount": "2222"}}],
                "meta": {"paging": {}, "count": {"actual": 1}},
            }),
        ]
        client = SchwabAdvisorClient(access_token="test_token")
        profiles = client.get_all_account_profiles()
        assert len(profiles) == 2
        assert profiles[0].formatted_account == "1111"
        assert profiles[1].formatted_account == "2222"
        assert mock_inst.request.call_count == 2

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_all_account_profiles_single_page(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": [{"attributes": {"formattedAccount": "1111"}}],
            "meta": {"paging": {}, "count": {}},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        profiles = client.get_all_account_profiles()
        assert len(profiles) == 1
        assert mock_inst.request.call_count == 1

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_all_account_profiles_empty(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {"data": [], "meta": {}})
        client = SchwabAdvisorClient(access_token="test_token")
        profiles = client.get_all_account_profiles()
        assert profiles == []


class TestTransactions:
    @patch("schwab_advisor.client.httpx.Client")
    def test_get_transactions(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": [{"id": "t1", "attributes": {"action": "MoneyLink Transfer", "amount": 100}}],
            "meta": {"paging": {}, "count": {"actual": 1}},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_transactions("93319284")
        assert isinstance(resp, TransactionsResponse)
        assert len(resp.transactions) == 1
        # Verify Schwab-Client-Ids header
        headers = mock_inst.request.call_args[1]["headers"]
        assert headers["Schwab-Client-Ids"] == "account=93319284"
        # Transactions caps page[limit] at 250 (not the usual 500) — a larger
        # value is a hard 400 from the sandbox. Guard the default.
        params = mock_inst.request.call_args[1]["params"]
        assert params["page[limit]"] == 250

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_transaction_detail(self, mock_client_cls):
        # TRDE-0001: the endpoint is addressed by executedDate+publishedDate
        # (both REQUIRED per spec — omitting either is a hard 400) and returns
        # a SINGLE record (data: {...}), not a list.
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": {"id": "d1", "type": "transaction-detail", "attributes": {
                "formattedAccount": "****1857", "description": "TEST",
                "amount": 120.56, "netAmount": 120.56, "commission": 1.25,
                "withholdingTax": 0.5, "executedDate": "2024-06-20",
                "settleDate": "2024-06-20",
            }},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_transaction_detail(
            "10001857", "2024-06-20", "2024-06-19T05:37:59.066235")
        assert isinstance(resp, TransactionDetail)
        assert resp.amount == 120.56
        assert resp.commission == 1.25
        assert resp.withholding_tax == 0.5
        params = mock_inst.request.call_args[1]["params"]
        assert params["filter[executedDate]"] == "2024-06-20"
        assert params["filter[publishedDate]"] == "2024-06-19T05:37:59.066235"
        assert params["showAccount"] == "Mask"
        headers = mock_inst.request.call_args[1]["headers"]
        assert headers["Schwab-Client-Ids"] == "account=10001857"

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_transaction_detail_show_account(self, mock_client_cls):
        # TRDE-0002: showAccount switches to Show on request.
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": {"id": "d1", "type": "transaction-detail",
                     "attributes": {"formattedAccount": "10001857"}},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_transaction_detail(
            "10001857", "2024-06-20", "2024-06-19T05:37:59.066235",
            show_account="Show")
        assert resp.formatted_account == "10001857"
        params = mock_inst.request.call_args[1]["params"]
        assert params["showAccount"] == "Show"


class TestAccountHolders:
    @patch("schwab_advisor.client.httpx.Client")
    def test_get_account_holder(self, mock_client_cls):
        # /profiles/account-holders returns a paginated list per OpenAPI;
        # filtering by accountHolderId in Schwab-Client-Ids returns a 1-item array.
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": [
                {"id": "15568272", "type": "account-holder", "attributes": {
                    "role": "LPOA",
                    "name": "TEST LPOA",
                    "firstName": "TEST",
                    "lastName": "LPOA",
                    "formattedDateOfBirth": "1983-12-10",
                    "citizenship": "US",
                    "employment": {"employmentStatus": "EMPLOYED"},
                }},
            ],
            "meta": {},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_account_holder("10001015", "15568272")
        assert isinstance(resp, AccountHoldersResponse)
        assert len(resp.holders) == 1
        assert resp.holders[0].first_name == "TEST"
        assert resp.holders[0].last_name == "LPOA"
        headers = mock_inst.request.call_args[1]["headers"]
        assert headers["Schwab-Client-Ids"] == "account=10001015,accountHolderId=15568272"

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_profiles(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": {"type": "profiles", "attributes": {
                "profiles": [{"formattedAccount": "1234"}],
            }},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_profiles(["1234", "5678"])
        body = mock_inst.request.call_args[1]["json"]
        assert body["Accounts"] == ["1234", "5678"]
        assert len(resp.profiles) == 1


class TestPreferences:
    @patch("schwab_advisor.client.httpx.Client")
    def test_get_preferences_and_authorizations(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": [{"attributes": {"formattedAccount": "1234"}}],
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_preferences_and_authorizations(["1234"])
        assert isinstance(resp, PreferencesAndAuthorizationsResponse)
        assert len(resp.items) == 1
        body = mock_inst.request.call_args[1]["json"]
        assert body["Accounts"] == ["1234"]
        # showAccount lives in the BODY, not the query string —
        # endpoint silently ignores the query-string form.
        assert body["showAccount"] == "Mask"

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_preferences_and_authorizations_show(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {"data": []})
        client = SchwabAdvisorClient(access_token="test_token")
        client.get_preferences_and_authorizations(["1234"], show_account="Show")
        body = mock_inst.request.call_args[1]["json"]
        assert body["showAccount"] == "Show"


class TestStandingAuthorizations:
    @patch("schwab_advisor.client.httpx.Client")
    def test_get_standing_instructions_returns_summary(self, mock_client_cls):
        # The list endpoint returns SUMMARY records (no counter-party);
        # mirrors real sandbox response shape verified live.
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": [
                {"id": "J-1293876388-2022", "type": "standing-instruction-summary",
                 "attributes": {
                     "masterAccount": 8174295, "account": 14217596,
                     "instructions": {
                         "nickname": "",
                         "transactionType": "J",
                         "direction": "Outgoing",
                         "hasIaAuthority": True,
                     },
                 }},
            ],
            "meta": {"paging": {"nextCursor": ""}, "count": {"actual": 1}},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_standing_instructions("8174295", "14217596")
        assert isinstance(resp, StandingInstructionsResponse)
        assert len(resp.instructions) == 1
        si = resp.instructions[0]
        assert si.id == "J-1293876388-2022"
        assert si.master_account == "8174295"
        assert si.account == "14217596"
        assert si.transaction_type == "J"
        assert si.direction == "Outgoing"
        assert si.has_ia_authority is True
        # Schwab-Client-Ids header should carry both masterAccount + account.
        headers = mock_inst.request.call_args[1]["headers"]
        assert headers["Schwab-Client-Ids"] == "masterAccount=8174295,account=14217596"

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_standing_instructions_empty(self, mock_client_cls):
        _setup_mock_client(mock_client_cls, {
            "data": [],
            "meta": {"paging": {"nextCursor": ""}, "count": {"total": 0, "actual": 0}},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_standing_instructions("8174295", "10001015")
        assert resp.instructions == []
        assert resp.next_cursor is None
        assert resp.total_count == 0

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_standing_instruction_returns_detail(self, mock_client_cls):
        # The /standing-instructions/{id} endpoint returns DETAIL with
        # the embedded counter-party — verified shape from sandbox live.
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": {
                "id": "J-1293876388-2022",
                "type": "standing-instruction-detail",
                "attributes": {
                    "masterAccount": 8174295, "account": 14217596,
                    "instructions": {
                        "nickname": "",
                        "transactionType": "A",
                        "direction": "Outgoing",
                        "counterParty": {
                            "routingNumber": "021000021",
                            "accountNumber": "1015-4509",
                            "name": "ACME",
                            "bankName": "JPMORGAN",
                            "phone": "212-555-1212",
                            "address": {
                                "address1": "100 Main St",
                                "address2": "",
                                "address3": "",
                                "countryCode": "USA",
                            },
                        },
                        "hasIaAuthority": True,
                    },
                },
            },
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_standing_instruction(
            "J-1293876388-2022", "8174295", "14217596",
        )
        assert isinstance(resp, StandingInstructionDetail)
        assert resp.id == "J-1293876388-2022"
        assert resp.transaction_type == "A"
        cp = resp.counter_party
        assert cp.routing_number == "021000021"
        assert cp.bank_name == "JPMORGAN"
        assert cp.account_number == "1015-4509"
        assert cp.address.address1 == "100 Main St"
        assert cp.address.country_code == "USA"
        # URL must include the path id.
        url = mock_inst.request.call_args[0][1]
        assert "/standing-instructions/J-1293876388-2022" in url


class TestNewEndpoints:
    @patch("schwab_advisor.client.httpx.Client")
    def test_get_master_accounts(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": [{"id": "8174295", "type": "master-account", "attributes": {
                "masterAccountName": "TEST FIRM", "masterAccountType": "FA",
            }}],
            "meta": {"paging": {}, "count": {"actual": 1, "total": 1}},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_master_accounts()
        assert isinstance(resp, MasterAccountsResponse)
        assert resp.master_accounts[0].id == "8174295"
        assert resp.master_accounts[0].master_account_name == "TEST FIRM"

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_accounts(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": [{"id": "10001015", "type": "account", "attributes": {
                "formattedMasterAccount": "8174295",
                "accountRegistrationType": "Indiv",
                "firstName": "TEST",
                "lastName": "USER",
                "clientIds": [803134686],
            }}],
            "meta": {"paging": {"nextCursor": "2"}, "count": {"actual": 1, "total": 84}},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_accounts(show_account="Show")
        assert isinstance(resp, AccountsResponse)
        assert resp.accounts[0].first_name == "TEST"
        assert resp.next_cursor == "2"

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_account_roles(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": [{"id": "abc", "attributes": {
                "formattedAccount": "1234", "formattedMasterAccount": "8174",
                "roles": [{"role": "CONTB", "firstName": "TEST"}],
            }}],
            "meta": {"paging": {}, "count": {"actual": 1}},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_account_roles()
        assert len(resp.account_roles) == 1
        assert len(resp.account_roles[0].roles) == 1
        # Default: showDOB/showTaxID/showAccount=Mask, no includeTotalCount
        params = mock_inst.request.call_args[1]["params"]
        assert params["showAccount"] == "Mask"
        assert params["showDOB"] == "Mask"
        assert params["showTaxID"] == "Mask"
        assert "includeTotalCount" not in params

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_account_roles_all_unmask_params(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": [], "meta": {},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        client.get_account_roles(
            include_total_count=True,
            show_account="Show", show_dob="Show", show_tax_id="Show",
        )
        params = mock_inst.request.call_args[1]["params"]
        assert params["showAccount"] == "Show"
        assert params["showDOB"] == "Show"
        assert params["showTaxID"] == "Show"
        assert params["includeTotalCount"] == "true"

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_account_rmd(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": [{"id": "abc", "attributes": {
                "formattedAccount": "1234", "isRothIra": False,
                "rmdCurrentYear": 5000.0, "currentYear": 2026,
            }}],
            "meta": {"paging": {}, "count": {"actual": 1}},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_account_rmd()
        assert resp.rmds[0].rmd_current_year == 5000.0

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_account_sync(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": [{"id": "uuid", "attributes": {
                "formattedAccount": "1234", "firstName": "TEST",
                "clientId": 803134686,
            }}],
            "meta": {"paging": {}, "count": {"actual": 1, "total": 88}},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_account_sync()
        assert resp.records[0].client_id == 803134686

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_balance_detail(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": [{"id": "uuid", "type": "balance-detail", "attributes": {
                "formattedAccount": "9284", "totalAccountValue": 1853622.91,
                "cash": 1768.46, "isMarginEnabled": False,
            }}],
            "meta": {},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_balance_detail("93319284")
        assert resp.balances[0].total_account_value == 1853622.91
        headers = mock_inst.request.call_args[1]["headers"]
        assert headers["Schwab-Client-Ids"] == "account=93319284"

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_balances_list(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": {"type": "balances", "attributes": {
                "balances": [{"formattedAccount": "9284", "totalAccountValue": 100}],
            }},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_balances_list(["93319284"])
        assert len(resp.balances) == 1
        body = mock_inst.request.call_args[1]["json"]
        assert body["Accounts"] == ["93319284"]
        # BALLISTPOST defaults: showAccount rides in the body as Mask;
        # includeOpenOrders / sortDirection are omitted until requested.
        assert body["showAccount"] == "Mask"
        assert "includeOpenOrders" not in body
        assert "sortDirection" not in body

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_balances_list_options(self, mock_client_cls):
        # BALLISTPOST-0002/0003/0004: the optional filters ride in the POST
        # body per the Balances spec's BalancesListPostRequest.
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": {"type": "balances", "attributes": {"balances": []}},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        client.get_balances_list(
            ["93319284", "10001857"], include_open_orders=True,
            sort_direction="Desc", show_account="Show")
        body = mock_inst.request.call_args[1]["json"]
        assert body["Accounts"] == ["93319284", "10001857"]
        assert body["includeOpenOrders"] is True
        assert body["sortDirection"] == "Desc"
        assert body["showAccount"] == "Show"

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_position_detail(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": {"type": "position-detail", "attributes": {
                "positions": [{"symbol": "AAPL", "quantity": 100}],
                "totalPositions": {"totalMarketValue": 15000},
            }},
            "meta": {"paging": {}, "count": {"actual": 1}},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_position_detail("93319284")
        assert len(resp.positions) == 1
        # v0.3.0: positions/totals are typed, not raw dicts.
        assert resp.positions[0].symbol == "AAPL"
        assert resp.positions[0].quantity == 100.0
        assert resp.total_positions.total_market_value == 15000

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_positions_list(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": {"type": "positions", "attributes": {
                "positions": [{"symbol": "AAPL"}],
            }},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_positions_list(["93319284"])
        assert len(resp.positions) == 1
        body = mock_inst.request.call_args[1]["json"]
        assert body["Accounts"] == ["93319284"]
        assert body["showAccount"] == "Mask"
        for absent in ("securityType", "symbol", "pageCursor", "pageLimit",
                       "sortBy", "sortDirection"):
            assert absent not in body

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_positions_list_options(self, mock_client_cls):
        # POLIPOST-0002..0005: filter/pagination/sort/masking are BODY fields
        # on this endpoint (PositionsListPostRequest), not query params.
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": {"type": "positions", "attributes": {"positions": []}},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        client.get_positions_list(
            ["93319284"], security_type="Equity", symbol="AAPL",
            page_cursor="3", page_limit=2, sort_by="MarketValue",
            sort_direction="Desc", show_account="Show")
        body = mock_inst.request.call_args[1]["json"]
        assert body["securityType"] == "Equity"
        assert body["symbol"] == "AAPL"
        assert body["pageCursor"] == "3"
        assert body["pageLimit"] == 2
        assert body["sortBy"] == "MarketValue"
        assert body["sortDirection"] == "Desc"
        assert body["showAccount"] == "Show"

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_reports(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": {"type": "account-reports", "attributes": {
                "reports": [{"reportName": "Monthly Statement", "reportType": "Statements"}],
            }},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_reports("93319284")
        assert len(resp.reports) == 1
        assert resp.reports[0]["reportName"] == "Monthly Statement"

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_cost_basis_account_preferences_master(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": {"type": "account-preferences", "attributes": {
                "summary": {"formattedMasterAccount": "8174295", "statementType": "Compact"},
                "details": [
                    {"formattedAccount": "14217596", "accountTitle": "PETER",
                     "accountingMethod": "HCLOT", "initialCostBasisSource": "Schwab",
                     "isNonTaxableAccount": True, "onGainLossTab": False},
                ],
            }},
            "meta": {"paging": {}, "count": {"actual": 1}},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_cost_basis_account_preferences(master_account="8174295")
        assert resp.summary["statementType"] == "Compact"
        assert len(resp.details) == 1
        assert resp.details[0].accounting_method == "HCLOT"
        assert resp.details[0].is_non_taxable_account is True
        headers = mock_inst.request.call_args[1]["headers"]
        assert headers["Schwab-Client-Ids"] == "masterAccount=8174295"

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_cost_basis_rgl(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": {"type": "rgl-transactions", "attributes": {
                "summary": {}, "transactions": [],
            }},
            "meta": {"paging": {}, "count": {"actual": 0}},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_cost_basis_rgl_transactions("93319284")
        assert resp.transactions == []
        # Verify page_limit default is 100 (not 500)
        params = mock_inst.request.call_args[1]["params"]
        assert params["page[limit]"] == 100

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_cost_basis_ugl(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": {"type": "ugl-positions", "attributes": {
                "summary": {}, "positions": [],
            }},
            "meta": {},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_cost_basis_ugl_positions("93319284")
        assert resp.positions == []

    @patch("schwab_advisor.client.httpx.Client")
    def test_search_clients(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": [{"id": 123, "type": "client-info", "attributes": {
                "firstName": "TEST", "lastName": "USER",
                "accountName": "Test Account",
            }}],
            "meta": {"count": {"actual": 1, "total": 1}},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.search_clients(first_name="TEST")
        assert len(resp.clients) == 1
        assert resp.clients[0].first_name == "TEST"
        headers = mock_inst.request.call_args[1]["headers"]
        assert headers["Schwab-Client-Ids"] == "firstName=TEST"

    @patch("schwab_advisor.client.httpx.Client")
    def test_search_clients_combined(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {"data": [], "meta": {}})
        client = SchwabAdvisorClient(access_token="test_token")
        client.search_clients(first_name="A", last_name="B")
        headers = mock_inst.request.call_args[1]["headers"]
        assert headers["Schwab-Client-Ids"] == "firstName=A,lastName=B"

    def test_search_clients_requires_name(self):
        client = SchwabAdvisorClient(access_token="test_token")
        with pytest.raises(ValueError, match="At least one"):
            client.search_clients()

    @patch("schwab_advisor.client.httpx.Client")
    def test_search_account_owners(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": {"type": "account-owners", "attributes": {
                "accountOwners": [{"firstName": "TEST", "formattedAccount": "1234"}],
            }},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.search_account_owners(first_name="TEST")
        assert len(resp.account_owners) == 1
        body = mock_inst.request.call_args[1]["json"]
        assert body["firstName"] == "TEST"

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_document_preferences(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": {"type": "document-preferences", "attributes": {
                "documentPreferences": [{"formattedAccount": "1234"}],
            }},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_document_preferences(["93319284"])
        assert len(resp.document_preferences) == 1
        body = mock_inst.request.call_args[1]["json"]
        assert body["Accounts"] == ["93319284"]
        assert body["showAccount"] == "Mask"

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_document_preferences_show(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": {"type": "document-preferences", "attributes": {
                "documentPreferences": [{"formattedAccount": "10001857"}],
            }},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        client.get_document_preferences(["10001857"], show_account="Show")
        body = mock_inst.request.call_args[1]["json"]
        # Verified live: body-form showAccount is honoured;
        # query-string form is silently ignored by the endpoint.
        assert body["showAccount"] == "Show"

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_address_changes(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {"data": [], "included": []})
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_address_changes()
        assert resp.changes == []
        assert resp.included == []
        # No Schwab-Client-Ids header (firm-level endpoint)
        headers = mock_inst.request.call_args[1]["headers"]
        assert "Schwab-Client-Ids" not in headers

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_address_changes_with_data(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": [{
                "id": "abc-uuid",
                "type": "address-change",
                "attributes": {
                    "actionSource": "ActionCenter",
                    "actionStatus": "Completed",
                    "createdDate": "2020-02-20T16:46:02.984",
                    "originalCustomerAddresses": [{"addressLine1": "123 Main"}],
                    "updatedCustomerAddresses": [{"addressLine1": "456 New St"}],
                },
                "relationships": {"firm": {"data": {"id": "71525", "type": "Firm"}}},
            }],
            "included": [{"id": "162669664", "type": "customer", "attributes": {"firstName": "John"}}],
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_address_changes(filter_status="Completed", include_customer=True)
        assert len(resp.changes) == 1
        assert resp.changes[0].action_status == "Completed"
        assert resp.changes[0].original_customer_addresses[0]["addressLine1"] == "123 Main"
        assert resp.changes[0].relationships["firm"]["data"]["id"] == "71525"
        assert len(resp.included) == 1
        params = mock_inst.request.call_args[1]["params"]
        assert params["filter[status]"] == "Completed"
        assert params["include"] == "customer"

    @patch("schwab_advisor.client.httpx.Client")
    def test_upload_manfees(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {"data": {}})
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.upload_manfees("dGVzdA==")
        body = mock_inst.request.call_args[1]["json"]
        assert body["Base64EncodedFileContent"] == "dGVzdA=="


# --- Context manager ---


class TestContextManager:
    @patch("schwab_advisor.client.httpx.Client")
    def test_enter_creates_client(self, mock_client_cls):
        client = SchwabAdvisorClient(access_token="test_token")
        assert client._client is None
        with client:
            assert client._client is not None
        mock_client_cls.return_value.close.assert_called_once()

    @patch("schwab_advisor.client.httpx.Client")
    def test_request_uses_persistent_client(self, mock_client_cls):
        mock_inner = MagicMock()
        mock_inner.request.return_value = _mock_response({"data": [], "meta": {}})
        mock_client_cls.return_value = mock_inner

        client = SchwabAdvisorClient(access_token="test_token")
        with client:
            client.get_alerts()
        mock_inner.request.assert_called_once()


# --- Error handling ---


class TestErrorHandling:
    @patch("schwab_advisor.client.httpx.Client")
    def test_http_error_raises(self, mock_client_cls):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401 Unauthorized", request=MagicMock(), response=mock_resp
        )
        mock_inst = MagicMock()
        mock_inst.request.return_value = mock_resp
        mock_client_cls.return_value = mock_inst

        client = SchwabAdvisorClient(access_token="test_token")
        with pytest.raises(httpx.HTTPStatusError):
            client.get_alerts()

    @patch("schwab_advisor.client.httpx.Client")
    def test_update_alert_non_204_parses_json(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls,
            {"data": {"id": "alert-1", "type": "alert"}}, status_code=200
        )
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.update_alert(123, "Unread")
        assert resp.id == "alert-1"
        assert resp.raw_data is not None
        body = mock_inst.request.call_args[1]["json"]
        assert body == {"action": "Unread"}


# --- Optional parameters on create methods ---


class TestOptionalParams:
    @patch("schwab_advisor.client.httpx.Client")
    def test_create_service_request_with_account(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls,
            {"data": {"id": "sr-1", "attributes": {}}}, status_code=201
        )
        client = SchwabAdvisorClient(access_token="test_token")
        client.create_service_request(
            topic_name="T", sub_topic_name="S", description="D",
            account="9999",
        )
        body = mock_inst.request.call_args[1]["json"]
        assert body["account"] == "9999"

    @patch("schwab_advisor.client.httpx.Client")
    def test_create_service_request_with_files(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls,
            {"data": {"id": "sr-1", "attributes": {}}}, status_code=201
        )
        client = SchwabAdvisorClient(access_token="test_token")
        client.create_service_request(
            topic_name="T", sub_topic_name="S", description="D",
            master_account="1234",
            files=[{"name": "doc.pdf", "base64EncodedFileContent": "base64..."}],
        )
        body = mock_inst.request.call_args[1]["json"]
        assert len(body["files"]) == 1
        assert body["files"][0]["name"] == "doc.pdf"

    @patch("schwab_advisor.client.httpx.Client")
    def test_post_status_events_with_documents(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {"data": {}})
        client = SchwabAdvisorClient(access_token="test_token")
        client.post_status_events(
            myq_case_id="CASE1", master_account="1234",
            documents=[{"name": "doc.pdf"}],
            status_object_id="obj-1",
        )
        body = mock_inst.request.call_args[1]["json"]
        assert body["documents"] == [{"name": "doc.pdf"}]
        assert body["statusObjectId"] == "obj-1"
        assert "message" not in body

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_alert_detail_without_master_account(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": {"id": 123, "attributes": {}},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        client.get_alert_detail(123)
        headers = mock_inst.request.call_args[1]["headers"]
        assert "Schwab-Client-Ids" not in headers

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_alerts_with_all_filters(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {"data": [], "meta": {}})
        client = SchwabAdvisorClient(access_token="test_token")
        client.get_alerts(
            filter_types=["UserAlert"],
            filter_subjects=["User ID Activation"],
            filter_start_date="2026-04-01",
            filter_end_date="2026-04-15",
            sort_by="CreatedDate",
            sort_direction="Asc",
            show_account="Show",
            page_limit=10,
        )
        params = mock_inst.request.call_args[1]["params"]
        assert params["filter[subjects]"] == "User ID Activation"
        assert params["filter[startDate]"] == "2026-04-01"
        assert params["filter[endDate]"] == "2026-04-15"
        assert params["sortDirection"] == "Asc"
        assert params["page[limit]"] == 10


# --- Extra header merging ---


class TestExtraHeaders:
    def test_extra_headers_merge(self):
        client = SchwabAdvisorClient(access_token="test_token")
        headers = client._get_headers(
            extra_headers={"Schwab-Client-Ids": "masterAccount=123"}
        )
        assert headers["Schwab-Client-Ids"] == "masterAccount=123"
        assert "Authorization" in headers


# --- Validation scenario coverage ---


class TestValidationFilters:
    """Covers params added for Schwab tech validation (case 9850)."""

    @patch("schwab_advisor.client.httpx.Client")
    def test_alerts_filter_status(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {"data": [], "meta": {}})
        client = SchwabAdvisorClient(access_token="test_token")
        client.get_alerts(filter_status="New")
        params = mock_inst.request.call_args[1]["params"]
        assert params["filter[status]"] == "New"

    @patch("schwab_advisor.client.httpx.Client")
    def test_alerts_filter_is_archived_true(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {"data": [], "meta": {}})
        client = SchwabAdvisorClient(access_token="test_token")
        client.get_alerts(filter_is_archived=True)
        assert mock_inst.request.call_args[1]["params"]["filter[isArchived]"] == "true"

    @patch("schwab_advisor.client.httpx.Client")
    def test_alerts_filter_is_archived_false(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {"data": [], "meta": {}})
        client = SchwabAdvisorClient(access_token="test_token")
        client.get_alerts(filter_is_archived=False)
        assert mock_inst.request.call_args[1]["params"]["filter[isArchived]"] == "false"

    @patch("schwab_advisor.client.httpx.Client")
    def test_alerts_filter_is_archived_none_absent(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {"data": [], "meta": {}})
        client = SchwabAdvisorClient(access_token="test_token")
        client.get_alerts(filter_is_archived=None)
        assert "filter[isArchived]" not in mock_inst.request.call_args[1]["params"]

    @patch("schwab_advisor.client.httpx.Client")
    def test_alerts_filter_origin_type(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {"data": [], "meta": {}})
        client = SchwabAdvisorClient(access_token="test_token")
        client.get_alerts(filter_origin_type="Copied")
        assert mock_inst.request.call_args[1]["params"]["filter[originType]"] == "Copied"

    @patch("schwab_advisor.client.httpx.Client")
    def test_alerts_filter_origin_type_none_absent(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {"data": [], "meta": {}})
        client = SchwabAdvisorClient(access_token="test_token")
        client.get_alerts()
        assert "filter[originType]" not in mock_inst.request.call_args[1]["params"]

    @patch("schwab_advisor.client.httpx.Client")
    def test_alerts_schwab_client_ids_header(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {"data": [], "meta": {}})
        client = SchwabAdvisorClient(access_token="test_token")
        client.get_alerts(schwab_client_ids={"masterAccount": "8174295"})
        headers = mock_inst.request.call_args[1]["headers"]
        assert headers["Schwab-Client-Ids"] == "masterAccount=8174295"

    @patch("schwab_advisor.client.httpx.Client")
    def test_alerts_schwab_client_ids_multiple(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {"data": [], "meta": {}})
        client = SchwabAdvisorClient(access_token="test_token")
        client.get_alerts(
            schwab_client_ids={"masterAccount": "8174295", "account": "1234"}
        )
        headers = mock_inst.request.call_args[1]["headers"]
        # No space after comma — Schwab rejects whitespace (verified sandbox).
        assert headers["Schwab-Client-Ids"] == "masterAccount=8174295,account=1234"

    @patch("schwab_advisor.client.httpx.Client")
    def test_alert_detail_combined_master_and_account(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": {"id": 1, "attributes": {}},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        client.get_alert_detail(1, master_account="8174295", account="93319284")
        headers = mock_inst.request.call_args[1]["headers"]
        assert headers["Schwab-Client-Ids"] == "masterAccount=8174295,account=93319284"

    @patch("schwab_advisor.client.httpx.Client")
    def test_alert_detail_show_account(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": {"id": 1, "attributes": {}},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        client.get_alert_detail(1, master_account="8174295", show_account="Show")
        assert mock_inst.request.call_args[1]["params"]["showAccount"] == "Show"

    @patch("schwab_advisor.client.httpx.Client")
    def test_alert_detail_default_show_account_mask(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": {"id": 1, "attributes": {}},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        client.get_alert_detail(1, master_account="8174295")
        assert mock_inst.request.call_args[1]["params"]["showAccount"] == "Mask"

    @patch("schwab_advisor.client.httpx.Client")
    def test_create_status_feed_all_new_params(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": {"id": "feed-1", "attributes": {"statusObjects": []}},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        client.create_status_feed(
            status=["New"],
            master_accounts=["8174295"],
            accounts=["12345678"],
            start_date="2026-02-01",
            end_date="2026-04-17",
            time_frame="LastUpdatedDate",
            categories=["Account Maintenance", "Move Money"],
            myq_case_id="WI-123456",
            service_request_confirmation_id="SR813637257",
            action_center_envelope_id="842993565",
            include_all_events=True,
            first_page_only=False,
        )
        body = mock_inst.request.call_args[1]["json"]
        # camelCase per AS Status OpenAPI spec
        assert body["masterAccounts"] == ["8174295"]
        assert body["accounts"] == ["12345678"]
        assert body["startDate"] == "2026-02-01"
        assert body["endDate"] == "2026-04-17"
        assert body["timeFrame"] == "LastUpdatedDate"
        assert body["categories"] == ["Account Maintenance", "Move Money"]
        assert body["myqCaseId"] == "WI-123456"
        assert body["serviceRequestConfirmationId"] == "SR813637257"
        assert body["actionCenterEnvelopeId"] == "842993565"
        assert body["includeAllEvents"] is True
        assert body["firstPageOnly"] is False

    @patch("schwab_advisor.client.httpx.Client")
    def test_create_status_feed_minimal_omits_optionals(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": {"id": "feed-1", "attributes": {"statusObjects": []}},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        client.create_status_feed(status=["New"])
        body = mock_inst.request.call_args[1]["json"]
        # Top-level keys are PascalCase (verified accepted in prod 2026-05).
        assert set(body.keys()) == {"Status", "ShowAccount"}

    @patch("schwab_advisor.client.httpx.Client")
    def test_correl_id_override_empty(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {"data": [], "meta": {}})
        client = SchwabAdvisorClient(access_token="test_token")
        client.get_alerts(correl_id="")
        headers = mock_inst.request.call_args[1]["headers"]
        assert headers["Schwab-Client-CorrelId"] == ""

    @patch("schwab_advisor.client.httpx.Client")
    def test_correl_id_override_custom(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {"data": [], "meta": {}})
        client = SchwabAdvisorClient(access_token="test_token")
        client.get_alerts(correl_id="trace-abc-123")
        headers = mock_inst.request.call_args[1]["headers"]
        assert headers["Schwab-Client-CorrelId"] == "trace-abc-123"

    @patch("schwab_advisor.client.httpx.Client")
    def test_correl_id_none_generates_uuid(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {"data": [], "meta": {}})
        client = SchwabAdvisorClient(access_token="test_token")
        client.get_alerts()
        headers = mock_inst.request.call_args[1]["headers"]
        # UUID4 is 36 chars with 4 dashes
        assert len(headers["Schwab-Client-CorrelId"]) == 36
        assert headers["Schwab-Client-CorrelId"].count("-") == 4

    @patch("schwab_advisor.client.httpx.Client")
    def test_correl_id_on_get_alert_detail(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": {"id": 1, "attributes": {}},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        client.get_alert_detail(1, master_account="X", correl_id="")
        assert mock_inst.request.call_args[1]["headers"]["Schwab-Client-CorrelId"] == ""

    @patch("schwab_advisor.client.httpx.Client")
    def test_correl_id_on_create_status_feed(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": {"id": "f", "attributes": {"statusObjects": []}},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        client.create_status_feed(status=["New"], correl_id="")
        assert mock_inst.request.call_args[1]["headers"]["Schwab-Client-CorrelId"] == ""

    @patch("schwab_advisor.client.httpx.Client")
    def test_correl_id_on_get_status_feed(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {"data": [], "meta": {}})
        client = SchwabAdvisorClient(access_token="test_token")
        client.get_status_feed("feed-1", correl_id="")
        assert mock_inst.request.call_args[1]["headers"]["Schwab-Client-CorrelId"] == ""

    @patch("schwab_advisor.client.httpx.Client")
    def test_correl_id_on_get_status_events(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {"data": []})
        client = SchwabAdvisorClient(access_token="test_token")
        client.get_status_events("feed-1", "obj-1", correl_id="")
        assert mock_inst.request.call_args[1]["headers"]["Schwab-Client-CorrelId"] == ""


class TestFormatClientIds:
    def test_single_key(self):
        assert (
            SchwabAdvisorClient._format_client_ids({"masterAccount": "8174295"})
            == "masterAccount=8174295"
        )

    def test_multiple_keys(self):
        # No space after comma — Schwab rejects whitespace with 400.
        result = SchwabAdvisorClient._format_client_ids(
            {"masterAccount": "8174295", "account": "1234"}
        )
        assert result == "masterAccount=8174295,account=1234"

    def test_drops_empty_values(self):
        result = SchwabAdvisorClient._format_client_ids(
            {"masterAccount": "8174295", "account": ""}
        )
        assert result == "masterAccount=8174295"


class TestPaginationInvariants:
    """Covers Schwab pagination behavior documented in the OpenAPI spec."""

    @patch("schwab_advisor.client.httpx.Client")
    def test_empty_next_cursor_normalized_to_none(self, mock_client_cls):
        """Per OpenAPI spec: nextCursor='' when no more records; we normalize
        to None so callers can use a single `is None` check."""
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": [{"id": 1, "attributes": {}}],
            "meta": {"paging": {"nextCursor": ""}, "count": {"actual": 1}},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_alerts(page_limit=5)
        assert resp.next_cursor is None

    @patch("schwab_advisor.client.httpx.Client")
    def test_populated_next_cursor_passes_through(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": [],
            "meta": {"paging": {"nextCursor": "1001"}, "count": {"actual": 0}},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_alerts(page_limit=5)
        assert resp.next_cursor == "1001"

    @patch("schwab_advisor.client.httpx.Client")
    def test_missing_next_cursor_is_none(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {"data": [], "meta": {}})
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_alerts(page_limit=5)
        assert resp.next_cursor is None


class TestSchwabErrorCode:
    def _exc_with_body(self, body):
        resp = MagicMock()
        resp.json.return_value = body
        return httpx.HTTPStatusError("err", request=MagicMock(), response=resp)

    def test_extracts_code(self):
        from schwab_advisor import schwab_error_code
        exc = self._exc_with_body(
            {"errors": [{"code": "SEC-0001", "title": "Unauthorized"}]}
        )
        assert schwab_error_code(exc) == "SEC-0001"

    def test_multiple_errors_returns_first(self):
        from schwab_advisor import schwab_error_code
        exc = self._exc_with_body({
            "errors": [
                {"code": "SEC-0002", "title": "Not Found"},
                {"code": "OTHER", "title": "Other"},
            ]
        })
        assert schwab_error_code(exc) == "SEC-0002"

    def test_no_errors_returns_none(self):
        from schwab_advisor import schwab_error_code
        exc = self._exc_with_body({})
        assert schwab_error_code(exc) is None

    def test_invalid_json_returns_none(self):
        from schwab_advisor import schwab_error_code
        resp = MagicMock()
        resp.json.side_effect = ValueError("not json")
        exc = httpx.HTTPStatusError("err", request=MagicMock(), response=resp)
        assert schwab_error_code(exc) is None

    def test_empty_errors_list_returns_none(self):
        from schwab_advisor import schwab_error_code
        exc = self._exc_with_body({"errors": []})
        assert schwab_error_code(exc) is None


class TestTypedRawDictMethods:
    """Coverage for the methods that previously returned raw dict and now
    return typed dataclasses. Field-level assertions catch silent
    under-parsing if the spec drifts."""

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_data_delivery_enrollment(self, mock_client_cls):
        _setup_mock_client(mock_client_cls, {
            "data": {"id": "ddfe-1", "type": "data-delivery-enrollment",
                     "attributes": {"enrolled": True}},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_data_delivery_enrollment()
        assert isinstance(resp, DataDeliveryEnrollmentResponse)
        assert resp.enrolled is True

    @patch("schwab_advisor.client.httpx.Client")
    def test_update_data_delivery_enrollment(self, mock_client_cls):
        # PUT returns 204 No Content; the method returns None. Guard the verb,
        # the users/v2 segment, and the flat {"enrolled": bool} body.
        mock_inst = _setup_mock_client(mock_client_cls, {}, status_code=204)
        client = SchwabAdvisorClient(access_token="test_token")
        result = client.update_data_delivery_enrollment(enrolled=False)
        assert result is None
        method, url = mock_inst.request.call_args[0][0], mock_inst.request.call_args[0][1]
        assert method == "PUT"
        assert "/users/v2/data-delivery-enrollments" in url
        assert mock_inst.request.call_args[1]["json"] == {"enrolled": False}

    @patch("schwab_advisor.client.httpx.Client")
    def test_update_data_delivery_enrollment_correl_id_override(self, mock_client_cls):
        # The correl_id param must thread onto the PUT (write) path too, so the
        # required-header validation case is expressible without touching _request.
        mock_inst = _setup_mock_client(mock_client_cls, {}, status_code=204)
        client = SchwabAdvisorClient(access_token="test_token")
        client.update_data_delivery_enrollment(enrolled=True, correl_id="")
        assert mock_inst.request.call_args[1]["headers"]["Schwab-Client-CorrelId"] == ""

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_move_money_activities(self, mock_client_cls):
        # AS Move Money Activity (no published spec): GET transfers/v1/activities,
        # Schwab-Client-Ids = account only, recurring/upcoming/recent buckets.
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": {"id": "act-1", "type": "activities", "attributes": {
                "formattedAccount": "****1857",
                "recurring": [],
                "upcoming": [],
                "recent": [{
                    "transactionId": "W-27855919-2696",
                    "transactionType": "Wire - 1st Party",
                    "direction": "Outgoing",
                    "toFrom": "Jpmorgan Chase  31903010",
                    "amount": 60.2,
                    "transactionDate": "2026-07-08",
                    "frequency": "ONREQST",
                    "status": "Pending",
                }],
            }},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_move_money_activities("10001857")
        assert isinstance(resp, MoveMoneyActivitiesResponse)
        assert resp.formatted_account == "****1857"
        assert len(resp.recent) == 1
        a = resp.recent[0]
        assert a.transaction_id == "W-27855919-2696"
        assert a.transaction_type == "Wire - 1st Party"
        assert a.direction == "Outgoing"
        assert a.amount == 60.2
        assert a.status == "Pending"
        # Verify the endpoint + account-only Schwab-Client-Ids header.
        method, url = mock_inst.request.call_args[0]
        headers = mock_inst.request.call_args[1]["headers"]
        assert method == "GET"
        assert "/transfers/v1/activities" in url
        assert headers["Schwab-Client-Ids"] == "account=10001857"
        # Spec (v2.0.0): ShowAccount (capital S) defaults to Mask; no
        # pagination params unless explicitly requested.
        params = mock_inst.request.call_args[1]["params"]
        assert params["ShowAccount"] == "Mask"
        assert "page[limit]" not in params

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_move_money_activities_select(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": {"id": "act-1", "type": "activities", "attributes": {
                "formattedAccount": "10001857",
                "recurring": [{
                    "transactionId": "A-1-2026", "transactionType": "ACH",
                    "direction": "Incoming", "toFrom": "BANK", "amount": 100.0,
                    "nextTransactionDate": "2026-08-01", "frequency": "MONTHLY",
                }],
            }},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_move_money_activities(
            "10001857", select="Recurring", show_account="Show",
        )
        params = mock_inst.request.call_args[1]["params"]
        assert params["select"] == "Recurring"
        assert params["ShowAccount"] == "Show"
        assert resp.recurring[0].next_transaction_date == "2026-08-01"
        assert resp.recurring[0].frequency == "MONTHLY"

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_tax_withholding_elections(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": {"id": "twe-1", "type": "tax-withholding-elections",
                     "attributes": {
                         "formattedAccount": "*****0120",
                         "isTaxWithholdingElected": True,
                         "isTaxWithholdingFederalOptedOut": False,
                         "taxWithholdingElectionFederal": 0.28,
                         "isTaxWithholdingStateOptedOut": False,
                         "taxWithholdingElectionState": 0.18,
                         "taxWithholdingStateCode": "CA",
                     }},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_tax_withholding_elections("10001857")
        assert resp.is_tax_withholding_elected is True
        assert resp.federal_election == 0.28
        assert resp.state_election == 0.18
        assert resp.state_code == "CA"
        method, url = mock_inst.request.call_args[0]
        headers = mock_inst.request.call_args[1]["headers"]
        assert method == "GET"
        assert "/transfers/v1/tax-withholding-elections" in url
        assert headers["Schwab-Client-Ids"] == "account=10001857"


class TestMoveMoneyTransfers:
    """AS Move Money Transfers — three POSTs that initiate money movement
    (spec: docs/schwab-move-money-transfers-openapi.json v1.0.0). The
    account travels in the BODY; no Schwab-Client-Ids header."""

    @patch("schwab_advisor.client.httpx.Client")
    def test_create_ach_transfer(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": {"id": "A-7788990011-2023", "type": "ach-transfer",
                     "attributes": {
                         "amount": 1000.5, "clientId": 123456789,
                         "direction": "Outgoing",
                         "formattedAccount": "*****1857",
                         "formattedMasterAccount": "*****4295",
                         "processDate": "2026-08-15",
                         "toFromAccount": {
                             "abaNumber": "021000021",
                             "accountName": "JOHN SMITH CHECKING",
                             "accountType": "CHECKING",
                             "financialInstitution": "JPMORGAN CHASE",
                             "formattedAccount": "*****3010",
                         },
                     }},
            "meta": {"warnings": [
                {"code": "W-001", "title": "Processing note",
                 "detail": "Process date adjusted to next business day."},
            ]},
        }, status_code=201)
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.create_ach_transfer(
            "A-1234567890-2021",
            account="10001857", client_id=123456789,
            amount=1000.5, process_date="2026-08-15",
        )
        assert resp.id == "A-7788990011-2023"
        assert resp.amount == 1000.5
        assert resp.direction == "Outgoing"
        assert resp.to_from_account is not None
        assert resp.to_from_account.aba_number == "021000021"
        assert len(resp.warnings) == 1
        assert resp.warnings[0].code == "W-001"
        method, url = mock_inst.request.call_args[0]
        body = mock_inst.request.call_args[1]["json"]
        headers = mock_inst.request.call_args[1]["headers"]
        assert method == "POST"
        assert "/transfers/v1/ach/standing-authorizations/A-1234567890-2021" in url
        assert body["account"] == 10001857  # spec type: integer
        assert body["clientId"] == 123456789
        assert body["processDate"] == "2026-08-15"
        assert "frequency" not in body  # one-time: omitted, not null
        assert "Schwab-Client-Ids" not in headers

    @patch("schwab_advisor.client.httpx.Client")
    def test_create_ach_transfer_recurring_retirement(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": {"id": "A-1-2026", "type": "ach-transfer", "attributes": {
                "frequency": "MONTHLY", "endDate": "2027-08-15",
                "retirementResponseDetails": {
                    "distributionReason": "NORMAL",
                    "grossNetIndicator": "G",
                    "netAmount": 720.0,
                    "taxWithholdingElectionFederal": 0.28,
                    "taxWithholdingFederalAmount": 280.0,
                    "totalWithdrawalAmount": 1000.0,
                    "year": "2026",
                },
            }},
        }, status_code=201)
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.create_ach_transfer(
            "A-1234567890-2021",
            account="10001857", client_id=1, amount=1000.0,
            process_date="2026-08-15", frequency="MONTHLY",
            end_date="2027-08-15",
            retirement_details={"year": "2026", "distributionReason": "NORMAL",
                                "grossNetIndicator": "G"},
        )
        body = mock_inst.request.call_args[1]["json"]
        assert body["frequency"] == "MONTHLY"
        assert body["endDate"] == "2027-08-15"
        assert body["retirementRequestDetails"]["distributionReason"] == "NORMAL"
        assert resp.frequency == "MONTHLY"
        assert resp.retirement_details is not None
        assert resp.retirement_details.net_amount == 720.0
        assert resp.retirement_details.federal_withholding_amount == 280.0

    @patch("schwab_advisor.client.httpx.Client")
    def test_create_wire_transfer_from_authorization(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": {"id": "W-5566778899-2023", "type": "wire-transfer",
                     "attributes": {
                         "caseId": "9912345", "status": "Pending eAuth",
                         "amount": 2500.0, "processDate": "2026-08-15",
                         "wireFee": 25.0,
                         "standingAuthorizationDetails": {"id": "W-1234567890-2021"},
                     }},
        }, status_code=201)
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.create_wire_transfer_from_authorization(
            "W-1234567890-2021",
            account="10001857", amount=2500.0, process_date="2026-08-15",
            transmission_note="Rent payment",
        )
        assert resp.id == "W-5566778899-2023"
        assert resp.case_id == "9912345"
        assert resp.status == "Pending eAuth"
        assert resp.wire_fee == 25.0
        body = mock_inst.request.call_args[1]["json"]
        assert "clientId" not in body  # wire-from-SLOA takes no clientId
        assert body["transmissionNote"] == "Rent payment"
        url = mock_inst.request.call_args[0][1]
        assert "/transfers/v1/wires/standing-authorizations/W-1234567890-2021" in url

    @patch("schwab_advisor.client.httpx.Client")
    def test_create_wire_transfer_freeform(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": {"id": "W-9988776655-2023", "type": "wire-transfer",
                     "attributes": {"status": "Pending eAuth", "amount": 500.0}},
        }, status_code=201)
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.create_wire_transfer(
            account="10001857", client_id=42, amount=500.0,
            process_date="2026-08-15", aba_number="021000021",
            recipient_bank={"account": "31903010",
                            "accountName": "JPMORGAN CHASE"},
            recipient={"account": "31903010",
                       "useModifiedAccountHolderName": False},
            intermediary_bank={"abaNumber": "026009593"},
        )
        assert resp.id == "W-9988776655-2023"
        body = mock_inst.request.call_args[1]["json"]
        assert body["abaNumber"] == "021000021"
        # Live field names (sandbox-verified 2026-07-14), NOT the spec's
        # recipientBankRequest/recipientPersonOrOrgRequest.
        assert body["recipientBank"]["accountName"] == "JPMORGAN CHASE"
        assert body["recipient"]["account"] == "31903010"
        assert body["intermediaryBank"]["abaNumber"] == "026009593"
        url = mock_inst.request.call_args[0][1]
        assert url.endswith("/transfers/v1/wires")


class TestTypedRawDictMethodsTail:
    """User-auth / orders / address-change methods that were the tail of
    TestTypedRawDictMethods before TestMoveMoneyTransfers was inserted
    between them. Same fixtures and conventions."""

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_user_authorizations(self, mock_client_cls):
        _setup_mock_client(mock_client_cls, {
            "data": {"id": "user-1", "type": "user-authorizations",
                     "attributes": {
                         "isUserFsa": True,
                         "authorizations": [
                             {"authorization": "Trading", "isAuthorized": True},
                             {"authorization": "AccountAccess", "isAuthorized": False},
                         ],
                     }},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_user_authorizations()
        assert isinstance(resp, UserAuthorizationsResponse)
        assert resp.is_user_fsa is True
        assert len(resp.authorizations) == 2
        assert resp.authorizations[0].authorization == "Trading"
        assert resp.authorizations[0].is_authorized is True
        assert resp.authorizations[1].is_authorized is False

    @patch("schwab_advisor.client.httpx.Client")
    def test_submit_orders_returns_typed(self, mock_client_cls):
        _setup_mock_client(mock_client_cls, {
            "data": {"id": "uuid-1", "type": "submit-order-response",
                     "attributes": {
                         "totalCount": 2,
                         "successfulCount": 1,
                         "fatalErrorCount": 1,
                         "informationalCount": 0,
                         "orderResults": [
                             {"clientOrderIdentifier": "c-1",
                              "orderNumber": "100",
                              "isOrderAccepted": True,
                              "validationErrors": []},
                             {"clientOrderIdentifier": "c-2",
                              "orderNumber": "",
                              "isOrderAccepted": False,
                              "validationErrors": [{"code": "X"}]},
                         ],
                     }},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.submit_orders(
            equity_order_items=[{"clientOrderIdentifier": "c-1"}],
            validate_only=True,
        )
        assert isinstance(resp, OrdersResponse)
        assert resp.total_count == 2
        assert resp.successful_count == 1
        assert resp.fatal_error_count == 1
        assert len(resp.order_results) == 2
        assert resp.order_results[0].is_order_accepted is True
        assert resp.order_results[0].order_number == "100"
        assert resp.order_results[1].is_order_accepted is False
        assert resp.order_results[1].validation_errors == [{"code": "X"}]

    @patch("schwab_advisor.client.httpx.Client")
    def test_submit_orders_sell_gets_default_tax_lot(self, mock_client_cls):
        mock = _setup_mock_client(mock_client_cls, {
            "data": {"id": "u", "type": "submit-order-response",
                     "attributes": {"totalCount": 1, "successfulCount": 1,
                                    "fatalErrorCount": 0,
                                    "informationalCount": 0,
                                    "orderResults": []}},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        client.submit_orders(equity_order_items=[
            {"clientOrderIdentifier": "c-1",
             "transactionType": {"type": "Sell"}},
            {"clientOrderIdentifier": "c-2",
             "transactionType": {"type": "Sell",
                                 "taxLot": {"taxLotMethod": "FIFO"}}},
            {"clientOrderIdentifier": "c-3",
             "transactionType": {"type": "Buy"}},
        ])
        body = mock.request.call_args.kwargs["json"]
        items = body["equityOrderItems"]
        # Bare Sell gets the "use the account default" taxLot injected.
        assert items[0]["transactionType"]["taxLot"] == {"taxLotMethod": "None"}
        # An explicit taxLot is left alone.
        assert items[1]["transactionType"]["taxLot"] == {"taxLotMethod": "FIFO"}
        # Buys are untouched.
        assert "taxLot" not in items[2]["transactionType"]

    @patch("schwab_advisor.client.httpx.Client")
    def test_cancel_orders_returns_typed(self, mock_client_cls):
        _setup_mock_client(mock_client_cls, {
            "data": {"id": "uuid-2", "type": "cancel-order-response",
                     "attributes": {
                         "totalCount": 1, "successfulCount": 1,
                         "fatalErrorCount": 0, "informationalCount": 0,
                         "orderResults": [
                             {"clientOrderIdentifier": "c-3",
                              "orderNumber": "200",
                              "isOrderAccepted": True},
                         ],
                     }},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.cancel_orders(equity_orders=[{"cancelOrderNumber": "200"}])
        assert isinstance(resp, OrdersResponse)
        assert resp.total_count == 1
        assert resp.order_results[0].order_number == "200"

    @patch("schwab_advisor.client.httpx.Client")
    def test_cancel_and_replace_orders_returns_typed(self, mock_client_cls):
        _setup_mock_client(mock_client_cls, {
            "data": {"id": "uuid-3", "type": "cancel-replace-order-response",
                     "attributes": {
                         "totalCount": 1, "successfulCount": 1,
                         "fatalErrorCount": 0, "informationalCount": 0,
                         "orderResults": [
                             {"clientOrderIdentifier": "c-4",
                              "orderNumber": "300",
                              "isOrderAccepted": True},
                         ],
                     }},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.cancel_and_replace_orders(
            equity_order_items=[{"cancelReplaceOrderNumber": "300"}],
        )
        assert isinstance(resp, OrdersResponse)
        assert resp.order_results[0].order_number == "300"

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_order_status_returns_typed_with_equity_and_mf(self, mock_client_cls):
        _setup_mock_client(mock_client_cls, {
            "data": {"id": "uuid-4", "type": "order-status-response",
                     "attributes": {
                         "totalOrders": 2,
                         "equityOrderStatusDetails": [
                             {"advisorId": "AD1", "orderNumber": "100",
                              "masterAccount": "8174295", "account": "10001857",
                              "status": "Filled", "symbol": "AAPL",
                              "cusip": "037833100", "quantity": 10,
                              "actualPrice": 175.5, "transactionType": "Buy",
                              "orderType": "Market", "duration": "Day"},
                         ],
                         "mutualFundOrderStatusDetails": [
                             {"advisorId": "AD1", "orderNumber": "101",
                              "masterAccount": "8174295", "account": "10001857",
                              "status": "Pending", "symbol": "VFINX",
                              "amount": 1000.0, "amountType": "Dollars",
                              "transactionType": "Buy"},
                         ],
                         "validationErrors": [],
                     }},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_order_status(
            account="10001857", from_date="2026-01-01", to_date="2026-12-31",
        )
        assert isinstance(resp, OrdersStatusResponse)
        assert resp.total_orders == 2
        assert len(resp.equity_order_status_details) == 1
        assert len(resp.mutual_fund_order_status_details) == 1
        eq = resp.equity_order_status_details[0]
        assert eq.symbol == "AAPL"
        assert eq.cusip == "037833100"
        assert eq.quantity == 10.0
        assert eq.actual_price == 175.5
        assert eq.transaction_type == "Buy"
        mf = resp.mutual_fund_order_status_details[0]
        assert mf.symbol == "VFINX"
        assert mf.amount == 1000.0
        assert mf.amount_type == "Dollars"

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_address_change_single_normalized(self, mock_client_cls):
        _setup_mock_client(mock_client_cls, {
            "data": {"id": "ac-1", "type": "address-change",
                     "attributes": {
                         "actionStatus": "Completed",
                         "createdDate": "2026-01-15",
                     }},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_address_change("ac-1")
        assert isinstance(resp, AddressChangesResponse)
        # JSON:API single-object data normalized to one-item list.
        assert len(resp.changes) == 1
        assert resp.changes[0].id == "ac-1"
        assert resp.changes[0].action_status == "Completed"

    @patch("schwab_advisor.client.httpx.Client")
    def test_create_address_change_returns_typed(self, mock_client_cls):
        _setup_mock_client(mock_client_cls, {
            "data": {"id": "ac-new", "type": "address-change",
                     "attributes": {"envelopeId": "env-789"}},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.create_address_change(
            master_account=8174295,
            user_entered_addresses=[{
                "addressLine1": "1 Main St", "city": "BOS",
                "state": "MA", "zipCode": "02101", "country": "US",
            }],
            customer_search_criteria={"firstName": "JOHN", "lastName": "DOE"},
        )
        assert isinstance(resp, AddressChangeCreateResponse)
        assert resp.id == "ac-new"
        assert resp.envelope_id == "env-789"


def _mock_per_url(mock_client_cls, url_responses: dict):
    """Mock httpx.Client.request to dispatch responses by URL substring.

    `url_responses` maps a URL substring (e.g. "/account-profiles") to
    the JSON the matching call should return. Used by tests for facade
    methods that fan out across multiple endpoints in one call.
    """
    mock_instance = MagicMock()

    def dispatch(method, url, *args, **kwargs):
        for needle, body in url_responses.items():
            if needle in url:
                # A MagicMock value is a pre-built response (e.g. from
                # _error_response); JSON bodies get wrapped as 200s.
                return body if isinstance(body, MagicMock) else _mock_response(body)
        raise AssertionError(f"unexpected URL: {url}")

    mock_instance.request.side_effect = dispatch
    mock_client_cls.return_value = mock_instance
    return mock_instance


class TestAccountFacade:
    """High-level account methods that fan out across multiple raw
    endpoints (list_accounts, get_account_detail, get_roles_for_account,
    get_slas_for_account)."""

    @patch("schwab_advisor.client.httpx.Client")
    def test_list_accounts_returns_summaries(self, mock_client_cls):
        _setup_mock_client(mock_client_cls, {
            "data": [
                {"id": "p1", "type": "account-profile", "attributes": {
                    "formattedAccount": "10001857",
                    "formattedMasterAccount": "8174295",
                    "accountTitle1": "JOHN SMITH",
                    "accountRegistrationType": "Individual",
                    "restrictionCodes": [],
                }},
                {"id": "p2", "type": "account-profile", "attributes": {
                    "formattedAccount": "10006285",
                    "formattedMasterAccount": "8174295",
                    "accountTitle1": "JANE DOE IRA",
                    "accountRegistrationType": "Roth IRA",
                    "restrictionCodes": ["TR-12"],
                }},
            ],
            "meta": {"paging": {"nextCursor": ""}, "count": {"actual": 2}},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        summaries = client.list_accounts(show_account="Show")
        assert len(summaries) == 2
        s = summaries[0]
        assert s.formatted_account == "10001857"
        assert s.formatted_master_account == "8174295"
        assert s.account_name == "JOHN SMITH"
        assert s.registration_type == "Individual"
        assert summaries[1].registration_type == "Roth IRA"
        assert summaries[1].restriction_codes == ["TR-12"]

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_account_detail_merges_apis(self, mock_client_cls):
        # Single non-IRA account ⇒ no RMD call should be made.
        _mock_per_url(mock_client_cls, {
            "/account-profiles": {
                "data": [{"id": "p1", "type": "account-profile", "attributes": {
                    "formattedAccount": "10001857",
                    "formattedMasterAccount": "8174295",
                    "accountTitle1": "JOHN SMITH",
                    "accountRegistrationType": "Individual",
                    "isMarginEnabled": True,
                    "restrictionCodes": [],
                }}],
                "meta": {"paging": {"nextCursor": ""}},
            },
            "/preferences-and-authorizations/list": {
                "data": [{"id": "10001857", "type": "preferences", "attributes": {
                    "formattedAccount": "10001857",
                    "accountPreferences": {
                        "isMarginEnabled": True,
                        "approvedOptionsLevel": "2",
                        "isMoneyLinkEnabled": True,
                    },
                    "authorizations": {
                        "isTradingAuthorizationEnabled": True,
                        "restrictionCodes": "",
                    },
                }}],
            },
            "/document-preferences/list": {
                "data": {"id": "dp", "type": "document-preferences", "attributes": {
                    "documentPreferences": [
                        {"formattedAccount": "10001857",
                         "deliveryPreferences": {"statements": "Electronic"}},
                    ],
                }},
            },
        })
        client = SchwabAdvisorClient(access_token="test_token")
        detail = client.get_account_detail("10001857")
        assert detail.formatted_account == "10001857"
        assert detail.formatted_master_account == "8174295"
        assert detail.account_name == "JOHN SMITH"
        assert detail.registration_type == "Individual"
        assert detail.profile is not None
        assert detail.profile.is_margin_enabled is True
        assert detail.preferences_and_authorizations is not None
        assert detail.preferences_and_authorizations.account_preferences.approved_options_level == "2"
        assert detail.document_preferences is not None
        # document_preferences is now a typed DocumentPreference, not a dict.
        assert detail.document_preferences.formatted_account == "10001857"
        # Non-IRA: rmd should be None and the call should be skipped.
        assert detail.rmd is None

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_account_detail_ira_fetches_rmd(self, mock_client_cls):
        _mock_per_url(mock_client_cls, {
            "/account-profiles": {
                "data": [{"id": "p1", "type": "account-profile", "attributes": {
                    "formattedAccount": "10006285",
                    "formattedMasterAccount": "8174295",
                    "accountTitle1": "JANE DOE IRA",
                    "accountRegistrationType": "Roth IRA",
                }}],
                "meta": {"paging": {"nextCursor": ""}},
            },
            "/preferences-and-authorizations/list": {"data": []},
            "/document-preferences/list": {"data": {"attributes": {
                "documentPreferences": [],
            }}},
            "/account-rmd": {
                "data": [{"id": "r1", "type": "account-rmd", "attributes": {
                    "formattedAccount": "10006285",
                    "isRothIra": True,
                    "rmdCurrentYear": 5000.0,
                    "currentYear": 2026,
                }}],
                "meta": {"paging": {"nextCursor": ""}},
            },
        })
        client = SchwabAdvisorClient(access_token="test_token")
        detail = client.get_account_detail("10006285")
        assert detail.rmd is not None
        assert detail.rmd.formatted_account == "10006285"
        assert detail.rmd.is_roth_ira is True

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_roles_for_account_filters(self, mock_client_cls):
        _setup_mock_client(mock_client_cls, {
            "data": [
                {"id": "ar1", "attributes": {
                    "formattedAccount": "10001857",
                    "formattedMasterAccount": "8174295",
                    "roles": [
                        {"accountHolderId": "h1", "role": "PrimaryAccountHolder",
                         "firstName": "JOHN"},
                    ],
                }},
                {"id": "ar2", "attributes": {
                    "formattedAccount": "10006285",
                    "formattedMasterAccount": "8174295",
                    "roles": [
                        {"accountHolderId": "h9", "role": "Beneficiary",
                         "firstName": "JANE"},
                    ],
                }},
            ],
            "meta": {"paging": {"nextCursor": ""}},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        roles = client.get_roles_for_account("10001857")
        assert len(roles) == 1
        assert roles[0].role == "PrimaryAccountHolder"
        assert roles[0].first_name == "JOHN"

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_roles_for_account_returns_empty_when_not_found(self, mock_client_cls):
        _setup_mock_client(mock_client_cls, {
            "data": [], "meta": {"paging": {"nextCursor": ""}},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        assert client.get_roles_for_account("99999999") == []

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_sloas_for_account_returns_list(self, mock_client_cls):
        _setup_mock_client(mock_client_cls, {
            "data": [
                {"id": "J-1293876388-2022", "attributes": {
                    "masterAccount": 8174295, "account": 10001857,
                    "instructions": {
                        "transactionType": "J",
                        "direction": "Outgoing",
                        "hasIaAuthority": True,
                    },
                }},
            ],
        })
        client = SchwabAdvisorClient(access_token="test_token")
        sloas = client.get_sloas_for_account("10001857", "8174295")
        assert len(sloas) == 1
        assert isinstance(sloas[0], StandingInstruction)
        assert sloas[0].transaction_type == "J"
        assert sloas[0].direction == "Outgoing"
        assert sloas[0].has_ia_authority is True

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_sloas_for_account_looks_up_master(self, mock_client_cls):
        # When master_account is omitted, the facade walks /account-profiles
        # to find the master for the given account before hitting
        # /standing-instructions.
        _mock_per_url(mock_client_cls, {
            "/account-profiles": {
                "data": [{"id": "p1", "attributes": {
                    "formattedAccount": "10001857",
                    "formattedMasterAccount": "8174295",
                }}],
                "meta": {"paging": {"nextCursor": ""}},
            },
            "/standing-instructions": {
                "data": [{"id": "A-540776344-0", "attributes": {
                    "masterAccount": 8174295, "account": 10001857,
                    "instructions": {
                        "transactionType": "A",
                        "direction": "Outgoing",
                        "hasIaAuthority": True,
                    },
                }}],
            },
        })
        client = SchwabAdvisorClient(access_token="test_token")
        sloas = client.get_sloas_for_account("10001857")  # no master arg
        assert len(sloas) == 1
        assert sloas[0].transaction_type == "A"

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_sloas_for_account_unknown_raises(self, mock_client_cls):
        _setup_mock_client(mock_client_cls, {
            "data": [], "meta": {"paging": {"nextCursor": ""}},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        with pytest.raises(ValueError, match="not found"):
            client.get_sloas_for_account("99999999")


_PRODUCT_GAP_WWW = (
    'Bearer realm="null",error="invalid_token",error_description='
    '"keymanagement.service.InvalidAPICallAsNoApiProductMatchFound: '
    'Invalid API call as no apiproduct match found"'
)

_INQUIRY_ACCOUNTS = {
    "data": [
        {"id": "10001857", "type": "account", "attributes": {
            "formattedMasterAccount": "8174295",
            "accountRegistrationType": "Individual",
            "accountTitle1": "JOHN SMITH",
            "lastName": "SMITH",
        }},
    ],
    "meta": {"paging": {"nextCursor": ""}, "count": {"actual": 1}},
}


class TestAccountFacadeSwapFallback:
    """The account facades must survive Schwab swapping which account
    product (AS Account bulk vs Account Inquiry) is attached to the app —
    the 2026-07-10 swap proved attachment can flip either way. The
    fallback keys on the product-not-attached 401 (the www-authenticate
    marker), NOT on generic errors."""

    @staticmethod
    def _requested_urls(mock_inst):
        urls = []
        for c in mock_inst.request.call_args_list:
            urls.append(c.kwargs.get("url") or (c.args[1] if len(c.args) > 1 else ""))
        return urls

    @patch("schwab_advisor.client.httpx.Client")
    def test_list_accounts_falls_back_to_account_inquiry(self, mock_client_cls):
        _mock_per_url(mock_client_cls, {
            "/account-profiles": _error_response(401, _PRODUCT_GAP_WWW),
            "/v2/accounts": _INQUIRY_ACCOUNTS,
        })
        client = SchwabAdvisorClient(access_token="test_token")
        summaries = client.list_accounts(show_account="Show")
        assert len(summaries) == 1
        s = summaries[0]
        assert s.formatted_account == "10001857"
        assert s.formatted_master_account == "8174295"
        assert s.account_name == "JOHN SMITH"
        assert s.registration_type == "Individual"
        assert s.restriction_codes == []  # Account Inquiry doesn't carry them

    @patch("schwab_advisor.client.httpx.Client")
    def test_list_accounts_propagates_token_401(self, mock_client_cls):
        """A plain 401 (bad/expired token) must raise, not silently
        switch source — both sources would 401 identically anyway."""
        mock_inst = _mock_per_url(mock_client_cls, {
            "/account-profiles": _error_response(
                401, 'Bearer realm="null",error="invalid_token"',
            ),
            "/v2/accounts": _INQUIRY_ACCOUNTS,
        })
        client = SchwabAdvisorClient(access_token="bad_token")
        with pytest.raises(httpx.HTTPStatusError):
            client.list_accounts()
        assert not any(
            "/v2/accounts" in u for u in self._requested_urls(mock_inst)
        ), "must not fall back on a non-product-gap 401"

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_account_detail_falls_back_for_summary_fields(self, mock_client_cls):
        """With AS Account detached: summary fields come from Account
        Inquiry, profile stays None, and the RMD facet (same product as
        profiles) degrades to None instead of raising."""
        _mock_per_url(mock_client_cls, {
            "/account-profiles": _error_response(401, _PRODUCT_GAP_WWW),
            "/account-rmd": _error_response(401, _PRODUCT_GAP_WWW),
            "/v2/accounts": {
                "data": [
                    {"id": "10006285", "type": "account", "attributes": {
                        "formattedMasterAccount": "8174295",
                        "accountRegistrationType": "Roth IRA",
                        "accountTitle1": "JANE DOE IRA",
                    }},
                ],
                "meta": {"paging": {"nextCursor": ""}},
            },
            "/preferences-and-authorizations/list": {
                "data": [{"id": "10006285", "type": "preferences", "attributes": {
                    "formattedAccount": "10006285",
                    "accountPreferences": {"isMarginEnabled": False},
                }}],
            },
            "/document-preferences/list": {
                "data": {"id": "dp", "type": "document-preferences", "attributes": {
                    "documentPreferences": [
                        {"formattedAccount": "10006285",
                         "deliveryPreferences": {"statements": "Electronic"}},
                    ],
                }},
            },
        })
        client = SchwabAdvisorClient(access_token="test_token")
        detail = client.get_account_detail("10006285")
        assert detail.formatted_account == "10006285"
        assert detail.formatted_master_account == "8174295"
        assert detail.account_name == "JANE DOE IRA"
        assert detail.registration_type == "Roth IRA"
        assert detail.profile is None
        assert detail.rmd is None  # rides the detached AS Account product
        assert detail.preferences_and_authorizations is not None
        assert detail.document_preferences is not None

    @patch("schwab_advisor.client.httpx.Client")
    def test_lookup_master_account_falls_back(self, mock_client_cls):
        """get_sloas_for_account without master_account resolves the
        master via Account Inquiry when profiles isn't attached."""
        _mock_per_url(mock_client_cls, {
            "/account-profiles": _error_response(401, _PRODUCT_GAP_WWW),
            "/v2/accounts": _INQUIRY_ACCOUNTS,
            "/standing-instructions": {
                "data": [], "meta": {"paging": {"nextCursor": ""}},
            },
        })
        client = SchwabAdvisorClient(access_token="test_token")
        sloas = client.get_sloas_for_account("10001857")  # no master arg
        assert sloas == []


class TestFacadeRobustness:
    """Not-found accounts raise; masked callers still get correct
    lookups; pagination survives a non-advancing cursor."""

    _EMPTY_PAGE = {"data": [], "meta": {"paging": {"nextCursor": ""}}}

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_account_detail_unknown_account_raises(self, mock_client_cls):
        _mock_per_url(mock_client_cls, {
            "/account-profiles": self._EMPTY_PAGE,
        })
        client = SchwabAdvisorClient(access_token="test_token")
        with pytest.raises(ValueError, match="not found"):
            client.get_account_detail("99999999")

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_account_detail_mask_still_finds_profile(self, mock_client_cls):
        """A Mask caller must still match: the profile lookup walks pages
        unmasked (masked page strings can never equal the unmasked input),
        while P&A / doc-prefs honor the caller's mask."""
        profile_page = {
            "data": [{"id": "p1", "type": "account-profile", "attributes": {
                "formattedAccount": "10001857",
                "formattedMasterAccount": "8174295",
                "accountTitle1": "JOHN SMITH",
                "accountRegistrationType": "Individual",
            }}],
            "meta": {"paging": {"nextCursor": ""}},
        }
        mock_inst = _mock_per_url(mock_client_cls, {
            "/account-profiles": profile_page,
            "/preferences-and-authorizations/list": {"data": []},
            "/document-preferences/list": {"data": {"attributes": {
                "documentPreferences": [],
            }}},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        detail = client.get_account_detail("10001857", show_account="Mask")
        assert detail.profile is not None
        assert detail.account_name == "JOHN SMITH"
        for call in mock_inst.request.call_args_list:
            url = call.kwargs.get("url") or call.args[1]
            if "/account-profiles" in url:
                assert call.kwargs["params"]["showAccount"] == "Show"
            if "/list" in url:
                assert call.kwargs["json"]["showAccount"] == "Mask"

    @patch("schwab_advisor.client.httpx.Client")
    def test_all_pages_stall_guard(self, mock_client_cls):
        """A server returning the same nextCursor forever must terminate,
        not loop unbounded."""
        stuck_page = {
            "data": [{"id": "p1", "type": "account-profile", "attributes": {
                "formattedAccount": "10001857",
            }}],
            "meta": {"paging": {"nextCursor": "STUCK"}},
        }
        mock_inst = _setup_mock_client(mock_client_cls, stuck_page)
        client = SchwabAdvisorClient(access_token="test_token")
        profiles = client.get_all_account_profiles()
        # page 1 (cursor None) + page 2 (cursor STUCK, same next) = 2 calls
        assert mock_inst.request.call_count == 2
        assert len(profiles) == 2

    @patch("schwab_advisor.client.httpx.Client")
    def test_find_paged_stall_guard(self, mock_client_cls):
        stuck_page = {
            "data": [{"id": "p1", "type": "account-profile", "attributes": {
                "formattedAccount": "OTHER",
            }}],
            "meta": {"paging": {"nextCursor": "STUCK"}},
        }
        mock_inst = _setup_mock_client(mock_client_cls, stuck_page)
        client = SchwabAdvisorClient(access_token="test_token")
        with pytest.raises(ValueError, match="not found"):
            client._lookup_master_account("10001857")
        assert mock_inst.request.call_count == 2


class TestClientLifecycleRobustness:
    def test_del_after_failed_init_is_quiet(self, monkeypatch):
        """__del__ must not raise AttributeError when __init__ failed
        before instance attributes were assigned."""
        monkeypatch.setenv("SCHWAB_ENVIRONMENT", "prod")  # invalid value
        with pytest.raises(ValueError):
            SchwabAdvisorClient()
        # The half-constructed instance is collected here; close() must
        # tolerate missing attributes (guarded via getattr).
        broken = object.__new__(SchwabAdvisorClient)
        broken.close()  # no AttributeError

    @patch("schwab_advisor.client.httpx.Client")
    def test_order_status_formatted_account_string(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {"data": {}})
        client = SchwabAdvisorClient(access_token="test_token")
        client.get_order_status(
            "1234-5678", from_date="2026-07-01", to_date="2026-07-17"
        )
        body = mock_inst.request.call_args.kwargs["json"]
        assert body["account"] == "1234-5678"
        assert "masterAccount" not in body

    @patch("schwab_advisor.client.httpx.Client")
    def test_order_status_numeric_coercion(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {"data": {}})
        client = SchwabAdvisorClient(access_token="test_token")
        client.get_order_status(
            "10001857",
            from_date="2026-07-01",
            to_date="2026-07-17",
            master_account="8174295",
        )
        body = mock_inst.request.call_args.kwargs["json"]
        assert body["account"] == 10001857
        assert body["masterAccount"] == 8174295


class TestProductNotAttached:
    """Direct tests for the Apigee product-gap marker predicate."""

    def _exc(self, status=401, www=""):
        response = MagicMock()
        response.status_code = status
        response.headers = {"www-authenticate": www} if www else {}
        return httpx.HTTPStatusError(
            "err", request=MagicMock(), response=response
        )

    def test_marker_present_401(self):
        exc = self._exc(www='error="invalid" error_description='
                        '"keymanagement.service.'
                        'InvalidAPICallAsNoApiProductMatchFound: no match"')
        assert product_not_attached(exc) is True

    def test_plain_401_no_header(self):
        assert product_not_attached(self._exc()) is False

    def test_marker_on_non_401_is_ignored(self):
        exc = self._exc(status=403, www="InvalidAPICallAsNoApiProductMatchFound")
        assert product_not_attached(exc) is False


class TestRemainingEndpointCoverage:
    @patch("schwab_advisor.client.httpx.Client")
    def test_get_all_accounts_multi_page(self, mock_client_cls):
        pages = [
            {"data": [{"id": "1", "attributes": {"formattedMasterAccount": "8"}}],
             "meta": {"paging": {"nextCursor": "c2"}}},
            {"data": [{"id": "2", "attributes": {"formattedMasterAccount": "8"}}],
             "meta": {"paging": {"nextCursor": ""}}},
        ]
        mock_inst = MagicMock()
        mock_inst.request.side_effect = [_mock_response(p) for p in pages]
        mock_client_cls.return_value = mock_inst
        client = SchwabAdvisorClient(access_token="test_token")
        accounts = client.get_all_accounts()
        assert [a.id for a in accounts] == ["1", "2"]
        # Second call must thread the cursor through.
        params2 = mock_inst.request.call_args_list[1].kwargs["params"]
        assert params2["page[cursor]"] == "c2"

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_report_pdf(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {
            "data": {"attributes": {"pdfFile": "JVBERi0="}},
        })
        client = SchwabAdvisorClient(access_token="test_token")
        resp = client.get_report_pdf("93319284", "r1", report_type="Statements")
        assert resp["data"]["attributes"]["pdfFile"] == "JVBERi0="
        call = mock_inst.request.call_args
        assert call.kwargs["params"]["reportId"] == "r1"
        assert call.kwargs["headers"]["Schwab-Client-Ids"] == "account=93319284"

    @patch("schwab_advisor.client.httpx.Client")
    def test_upload_blotters(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {}, status_code=204)
        client = SchwabAdvisorClient(access_token="test_token")
        client.upload_blotters("QkxPVA==")
        call = mock_inst.request.call_args
        assert call.kwargs["json"] == {"base64EncodedFileContent": "QkxPVA=="}
        url = call.kwargs.get("url") or call.args[1]
        assert "/upload-blotters" in url

    @patch("schwab_advisor.client.httpx.Client")
    def test_upload_allocations(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {}, status_code=204)
        client = SchwabAdvisorClient(access_token="test_token")
        client.upload_allocations("QUxMT0M=", master_account=8174295)
        body = mock_inst.request.call_args.kwargs["json"]
        assert body["masterAccount"] == 8174295


class TestPublicExports:
    def test_client_return_types_importable_from_root(self):
        """Every response type a public client method returns must be
        importable from the package root (and listed in __all__)."""
        import inspect as _inspect

        import schwab_advisor as root
        from schwab_advisor.client import SchwabAdvisorClient as C

        missing = set()
        for _, meth in _inspect.getmembers(C, _inspect.isfunction):
            if meth.__name__.startswith("_"):
                continue
            ret = _inspect.signature(meth).return_annotation
            for name in str(ret).replace("|", " ").split():
                name = name.strip("'\" ").split(".")[-1]
                if (
                    name
                    and name not in ("None", "Literal", "Optional")
                    and name[0].isupper()
                    and name.isidentifier()
                    and not hasattr(root, name)
                ):
                    missing.add(name)
        assert not missing, f"missing from package root: {sorted(missing)}"
        assert sorted(root.__all__) == root.__all__  # stays sorted


class TestClientIdsHeaderValidation:
    """Values that would corrupt the Schwab-Client-Ids pair structure or
    crash httpx's header encoding fail with a clear ValueError instead
    of a misleading Schwab 400 / UnicodeEncodeError."""

    def test_comma_value_raises(self):
        client = SchwabAdvisorClient(access_token="test_token")
        with pytest.raises(ValueError, match="Schwab-Client-Ids"):
            client.search_clients(last_name="Smith, Jr")

    def test_equals_value_raises(self):
        client = SchwabAdvisorClient(access_token="test_token")
        with pytest.raises(ValueError, match="Schwab-Client-Ids"):
            client.search_clients(last_name="a=b")

    def test_non_latin1_value_raises(self):
        client = SchwabAdvisorClient(access_token="test_token")
        with pytest.raises(ValueError, match="non-latin-1"):
            client.search_clients(last_name="Łukasz")

    def test_control_char_value_raises(self):
        client = SchwabAdvisorClient(access_token="test_token")
        with pytest.raises(ValueError, match="control"):
            client.search_clients(last_name="a\r\nX-Evil: 1")

    @patch("schwab_advisor.client.httpx.Client")
    def test_plain_space_in_value_still_allowed(self, mock_client_cls):
        """Only structural characters are rejected — a space INSIDE a
        value isn't the sandbox-verified whitespace-after-comma 400, so
        it passes through (server behavior unprobeable until Client
        Inquiry is entitled in sandbox)."""
        mock_inst = _setup_mock_client(mock_client_cls, {"data": []})
        client = SchwabAdvisorClient(access_token="test_token")
        client.search_clients(last_name="VAN DER BERG")
        headers = mock_inst.request.call_args.kwargs["headers"]
        assert headers["Schwab-Client-Ids"] == "lastName=VAN DER BERG"

    @patch("schwab_advisor.client.httpx.Client")
    def test_search_clients_multi_field_header(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {"data": []})
        client = SchwabAdvisorClient(access_token="test_token")
        client.search_clients(first_name="TEST", last_name="DOE")
        headers = mock_inst.request.call_args.kwargs["headers"]
        assert headers["Schwab-Client-Ids"] == "firstName=TEST,lastName=DOE"

    def test_search_clients_no_criteria_raises(self):
        client = SchwabAdvisorClient(access_token="test_token")
        with pytest.raises(ValueError, match="At least one"):
            client.search_clients()


class TestRound4Parameters:
    """Round-4 wrapper gaps: parameters the OpenAPI specs declare but the
    client did not send, and nested-wrapper responses that dropped their
    error/paging channels. Verified live against the sandbox 2026-07-30.
    """

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_accounts_sends_filter_sort_and_tax_id(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {"data": []})
        client = SchwabAdvisorClient(access_token="test_token")
        client.get_accounts(
            filter_is_iip="NonIIP", sort_by="AccountTitle1",
            sort_direction="Desc", show_tax_id="Show",
        )
        params = mock_inst.request.call_args[1]["params"]
        assert params["filter[isIip]"] == "NonIIP"
        assert params["sortBy"] == "AccountTitle1"
        assert params["sortDirection"] == "Desc"
        assert params["showTaxID"] == "Show"

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_accounts_omits_unset_optionals(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {"data": []})
        client = SchwabAdvisorClient(access_token="test_token")
        client.get_accounts()
        params = mock_inst.request.call_args[1]["params"]
        for key in ("filter[isIip]", "sortBy", "sortDirection", "showTaxID"):
            assert key not in params

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_accounts_show_tax_id_independent_of_show_account(self, mock_client_cls):
        """showTaxID governs the taxpayer id, showAccount the account
        number — a caller must be able to mask one and show the other."""
        mock_inst = _setup_mock_client(mock_client_cls, {"data": []})
        client = SchwabAdvisorClient(access_token="test_token")
        client.get_accounts(show_account="Mask", show_tax_id="Show")
        params = mock_inst.request.call_args[1]["params"]
        assert params["showAccount"] == "Mask"
        assert params["showTaxID"] == "Show"

    @patch("schwab_advisor.client.httpx.Client")
    def test_search_clients_sends_sort_params(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {"data": []})
        client = SchwabAdvisorClient(access_token="test_token")
        client.search_clients(last_name="DOE", sort_by="AccountName",
                              sort_direction="Desc")
        params = mock_inst.request.call_args[1]["params"]
        assert params["sortBy"] == "AccountName"
        assert params["sortDirection"] == "Desc"

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_profiles_sends_body_options(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {"data": {}})
        client = SchwabAdvisorClient(access_token="test_token")
        client.get_profiles(["111", "222"], include_iip="NonIIP",
                            show_account="Show")
        body = mock_inst.request.call_args[1]["json"]
        assert body["Accounts"] == ["111", "222"]
        assert body["includeIip"] == "NonIIP"
        assert body["showAccount"] == "Show"

    @patch("schwab_advisor.client.httpx.Client")
    def test_get_profiles_omits_unset_body_options(self, mock_client_cls):
        mock_inst = _setup_mock_client(mock_client_cls, {"data": {}})
        client = SchwabAdvisorClient(access_token="test_token")
        client.get_profiles(["111"])
        body = mock_inst.request.call_args[1]["json"]
        assert body == {"Accounts": ["111"]}

    def test_profiles_response_surfaces_invalid_accounts(self):
        """The error channel was previously discarded, so a partially
        failed batch looked like a clean success."""
        resp = ProfilesListResponse.from_dict({
            "data": {"id": "x", "type": "profiles", "attributes": {
                "profiles": [{"accountTitle": "A"}],
                "errors": {"invalidAccounts": ["****3226", "****0691"]},
            }},
            "meta": {"paging": {"nextCursor": "3"}, "count": {"total": 9}},
        })
        assert len(resp.profiles) == 1
        assert resp.invalid_accounts == ["****3226", "****0691"]
        assert resp.next_cursor == "3"
        assert resp.total_count == 9

    def test_profiles_response_handles_absent_error_channel(self):
        resp = ProfilesListResponse.from_dict({
            "data": {"attributes": {"profiles": [{"accountTitle": "A"}]}},
        })
        assert resp.invalid_accounts == []
        assert resp.next_cursor is None

    def test_reports_response_surfaces_paging(self):
        resp = ReportsResponse.from_dict({
            "data": {"id": "x", "type": "account-reports", "attributes": {
                "reports": [{"reportId": "abc", "reportName": "1099"}],
            }},
            "meta": {"paging": {"nextCursor": "2"}, "count": {"total": 5}},
        })
        assert resp.reports[0]["reportName"] == "1099"
        assert resp.next_cursor == "2"
        assert resp.total_count == 5

    def test_reports_response_exhausted_cursor_is_none(self):
        """Schwab sends nextCursor="" when there are no more pages."""
        resp = ReportsResponse.from_dict({
            "data": {"attributes": {"reports": []}},
            "meta": {"paging": {"nextCursor": ""}, "count": {"total": 0}},
        })
        assert resp.next_cursor is None

    def test_account_owner_list_surfaces_invalid_accounts(self):
        resp = AccountOwnerListResponse.from_dict({
            "data": {"id": "x", "type": "account-owners", "attributes": {
                "accountOwners": [{"firstName": "FIRST", "lastName": "LAST"}],
                "errors": {"invalidAccounts": ["****1015"]},
            }},
            "meta": {"paging": {"nextCursor": ""}, "count": {"total": 1}},
        })
        assert resp.account_owners[0]["lastName"] == "LAST"
        assert resp.invalid_accounts == ["****1015"]
        assert resp.next_cursor is None
        assert resp.total_count == 1
