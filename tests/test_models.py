"""Tests for data model from_dict parsing."""

import functools
import os
from pathlib import Path

import pytest

# Two suites below diff the models against Schwab's OpenAPI specifications.
# Those specs are Schwab's to distribute, not ours, so they are not carried
# in this repository. Point SCHWAB_SPECS_DIR at a checkout that has them to
# run the coverage guard; without it those suites skip and every other model
# test runs normally.
_SPECS_ENV = os.environ.get("SCHWAB_SPECS_DIR")
SPECS_DIR = Path(_SPECS_ENV) if _SPECS_ENV else None
requires_specs = pytest.mark.skipif(
    SPECS_DIR is None or not SPECS_DIR.is_dir(),
    reason="OpenAPI specs not in this repo; set SCHWAB_SPECS_DIR to run the "
           "schema-coverage guard",
)

from schwab_advisor.models import (  # noqa: E402
    AccountHolder,
    AccountHoldersResponse,
    AccountProfile,
    AccountProfilesResponse,
    AddressChangeCreateResponse,
    AddressChangesResponse,
    Address,
    Alert,
    AlertArchiveResponse,
    AlertDetail,
    AlertDetailResponse,
    AlertUpdateResponse,
    ArchiveDetail,
    Authorization,
    DataDeliveryEnrollmentResponse,
    MoveMoneyActivitiesResponse,
    MoveMoneyActivity,
    OrderResult,
    OrderStatusDetail,
    OrdersResponse,
    OrdersStatusResponse,
    PreferencesAndAuthorizations,
    PreferencesAndAuthorizationsResponse,
    ServiceRequestCreateResponse,
    ServiceRequestTopic,
    ServiceRequestTopicsResponse,
    StandingInstruction,
    StandingInstructionDetail,
    StandingInstructionsResponse,
    StatusEvent,
    StatusEventsPostResponse,
    StatusEventsResponse,
    StatusFeedCreateResponse,
    StatusFeedResponse,
    StatusObject,
    SubTopic,
    Transaction,
    TransactionsResponse,
    UserAuthorizationsResponse,
    _parse_meta,
)


# --- Alert ---


class TestAlert:
    def test_from_dict_with_attributes(self):
        data = {
            "id": 15157510,
            "type": "alert",
            "attributes": {
                "formattedMasterAccount": "8174295",
                "category": "ALERT",
                "typeCode": "USR-ALERT",
                "type": "User Alert",
                "subject": "User ID Reactivated",
                "status": "Viewed",
                "createdDate": "2024-10-16T17:18:55",
                "source": "MF_FILE",
                "priority": "INFO",
                "isArchived": False,
            },
        }
        alert = Alert.from_dict(data)
        assert alert.id == 15157510
        assert alert.formatted_master_account == "8174295"
        assert alert.alert_type == "User Alert"
        assert alert.type_code == "USR-ALERT"
        assert alert.subject == "User ID Reactivated"
        assert alert.status == "Viewed"
        assert alert.is_archived is False

    def test_from_dict_empty(self):
        alert = Alert.from_dict({})
        assert alert.id == ""
        assert alert.alert_type == ""

    def test_from_dict_with_new_spec_fields(self):
        """accountDescription + externalSystemRefId from official API spec."""
        data = {
            "id": 16054502,
            "type": "alert",
            "attributes": {
                "formattedAccount": "*****0120",
                "accountTitle": "GALE MORGAN BUSH-STONE",
                "accountDescription": "Gale Account",
                "externalSystemRefId": "A602",
            },
        }
        alert = Alert.from_dict(data)
        assert alert.account_description == "Gale Account"
        assert alert.external_system_ref_id == "A602"

    def test_sac_url_synthesized_from_id(self):
        alert = Alert.from_dict({"id": 294911594, "type": "alert", "attributes": {}})
        assert alert.sac_url == (
            "https://si2.schwabinstitutional.com/SI2/Home/default.aspx"
            "?display=details&index=0&alertId=294911594&tab=alerts"
        )

    def test_sac_url_empty_when_no_id(self):
        alert = Alert.from_dict({})
        assert alert.sac_url == ""


# --- Alert Detail ---


class TestAlertDetail:
    def test_from_dict_with_attributes(self):
        data = {
            "id": 15157510,
            "type": "alert-detail",
            "attributes": {
                "formattedMasterAccount": "***4295",
                "category": "ALERT",
                "type": "User Alert",
                "subject": "User ID Reactivated",
                "status": "Viewed",
                "detailText": "<html>...</html>",
                "detailType": "HTML",
                "statusHistory": [
                    {
                        "status": "New",
                        "statusDate": "2024-10-16",
                        "formattedMasterAccount": "***4295",
                        "userId": "abc123",
                        "lastName": "DOE",
                    }
                ],
            },
        }
        detail = AlertDetail.from_dict(data)
        assert detail.id == 15157510
        assert detail.alert_type == "User Alert"
        assert detail.detail_text == "<html>...</html>"
        assert len(detail.status_history) == 1
        # status_history is now a list of typed StatusHistoryEntry, not dict.
        sh = detail.status_history[0]
        assert sh.status == "New"
        assert sh.status_date == "2024-10-16"
        assert sh.formatted_master_account == "***4295"
        assert sh.user_id == "abc123"
        assert sh.last_name == "DOE"

    def test_from_dict_empty(self):
        detail = AlertDetail.from_dict({})
        assert detail.id == ""
        assert detail.status_history == []

    def test_from_dict_with_new_spec_fields(self):
        """Detail fields that weren't in the old model: formattedAccount,
        externalSystemRefId, audit/viewed/archived user+lastName+date."""
        data = {
            "id": 16054502,
            "type": "alert-detail",
            "attributes": {
                "formattedAccount": "*****0120",
                "formattedMasterAccount": "***3045",
                "externalSystemRefId": "AM-174788690",
                "auditUserId": "AlertsSystem",
                "auditLastName": "LANG",
                "viewedUserId": "user_1",
                "viewedLastName": "LANG",
                "archivedDate": "2022-05-13T06:37:37",
                "archivedUserId": "user_1",
                "archivedLastName": "LANG",
            },
        }
        d = AlertDetail.from_dict(data)
        assert d.formatted_account == "*****0120"
        assert d.external_system_ref_id == "AM-174788690"
        assert d.audit_user_id == "AlertsSystem"
        assert d.audit_last_name == "LANG"
        assert d.viewed_user_id == "user_1"
        assert d.viewed_last_name == "LANG"
        assert d.archived_date == "2022-05-13T06:37:37"
        assert d.archived_user_id == "user_1"
        assert d.archived_last_name == "LANG"

    def test_sac_url_synthesized_from_id(self):
        detail = AlertDetail.from_dict({
            "id": 232945397,
            "type": "alert-detail",
            "attributes": {"detailType": "HTML"},
        })
        assert detail.sac_url == (
            "https://si2.schwabinstitutional.com/SI2/Home/default.aspx"
            "?display=details&index=0&alertId=232945397&tab=alerts"
        )


class TestSacAlertUrl:
    def test_int_id(self):
        from schwab_advisor.models import sac_alert_url
        assert sac_alert_url(294911594) == (
            "https://si2.schwabinstitutional.com/SI2/Home/default.aspx"
            "?display=details&index=0&alertId=294911594&tab=alerts"
        )

    def test_str_id(self):
        from schwab_advisor.models import sac_alert_url
        assert "alertId=12345" in sac_alert_url("12345")

    def test_empty_id(self):
        from schwab_advisor.models import sac_alert_url
        assert sac_alert_url("") == ""
        assert sac_alert_url(None) == ""  # type: ignore[arg-type]

    def test_exported_from_package(self):
        from schwab_advisor import sac_alert_url
        assert "alertId=42" in sac_alert_url(42)


class TestAlertDetailResponse:
    def test_from_dict_with_data(self):
        data = {
            "data": {
                "id": 15157510,
                "type": "alert-detail",
                "attributes": {"type": "User Alert"},
            }
        }
        resp = AlertDetailResponse.from_dict(data)
        assert resp.alert is not None
        assert resp.alert.id == 15157510

    def test_from_dict_no_data(self):
        resp = AlertDetailResponse.from_dict({})
        assert resp.alert is None


class TestAlertArchiveResponse:
    def test_from_dict(self):
        data = {
            "data": {
                "id": "9d76e773-15bb-4005-8fa1-decd23d124ae",
                "type": "alerts-archive",
                "attributes": {
                    "areAllArchived": True,
                    "archiveDetails": [
                        {
                            "alertId": 15157526,
                            "hasArchivedStatusChanged": True,
                            "noArchivedStatusChangeReason": "",
                        }
                    ],
                },
            }
        }
        resp = AlertArchiveResponse.from_dict(data)
        assert resp.id == "9d76e773-15bb-4005-8fa1-decd23d124ae"
        assert resp.are_all_archived is True
        assert len(resp.archive_details) == 1
        assert resp.archive_details[0].alert_id == 15157526
        assert resp.archive_details[0].has_status_changed is True

    def test_previously_archived_reason(self):
        """Docs example: noArchivedStatusChangeReason='Previously Archived'."""
        data = {
            "data": {
                "id": "batch-uuid",
                "attributes": {
                    "areAllArchived": True,
                    "archiveDetails": [{
                        "alertId": 1556881,
                        "hasArchivedStatusChanged": False,
                        "noArchivedStatusChangeReason": "Previously Archived",
                    }],
                },
            }
        }
        resp = AlertArchiveResponse.from_dict(data)
        assert resp.archive_details[0].no_change_reason == "Previously Archived"
        assert resp.archive_details[0].has_status_changed is False

    def test_from_dict_empty(self):
        resp = AlertArchiveResponse.from_dict({})
        assert resp.id == ""
        assert resp.are_all_archived is False
        assert resp.archive_details == []


class TestAlertUpdateResponse:
    def test_from_dict(self):
        data = {"data": {"id": "alert-1", "type": "alert"}}
        resp = AlertUpdateResponse.from_dict(data)
        assert resp.id == "alert-1"

    def test_no_content(self):
        resp = AlertUpdateResponse(id="123", raw_data=None)
        assert resp.id == "123"


# --- Service Request Topics ---


class TestSubTopic:
    def test_from_dict(self):
        data = {
            "name": "Brokerage",
            "isAttachmentAllowed": True,
            "isAttachmentRequired": True,
            "maxAttachmentSize": 30,
        }
        st = SubTopic.from_dict(data)
        assert st.name == "Brokerage"
        assert st.is_attachment_required is True
        assert st.max_attachment_size == 30


class TestServiceRequestTopic:
    def test_from_dict(self):
        data = {
            "id": "55df8198",
            "type": "service-request-topic",
            "attributes": {
                "name": "Open New Account",
                "order": 1,
                "subTopics": [
                    {"name": "Brokerage", "isAttachmentAllowed": True,
                     "isAttachmentRequired": True, "maxAttachmentSize": 30},
                ],
            },
        }
        topic = ServiceRequestTopic.from_dict(data)
        assert topic.id == "55df8198"
        assert topic.name == "Open New Account"
        assert topic.order == 1
        assert len(topic.sub_topics) == 1
        assert topic.sub_topics[0].name == "Brokerage"


class TestServiceRequestTopicsResponse:
    def test_from_dict(self):
        data = {
            "data": [
                {"id": "1", "attributes": {"name": "Topic A", "order": 1, "subTopics": []}},
                {"id": "2", "attributes": {"name": "Topic B", "order": 2, "subTopics": []}},
            ]
        }
        resp = ServiceRequestTopicsResponse.from_dict(data)
        assert len(resp.topics) == 2
        assert resp.topics[0].name == "Topic A"


class TestServiceRequestCreateResponse:
    def test_from_dict(self):
        data = {
            "data": {
                "id": "SR378912733804863",
                "type": "service-request",
                "attributes": {
                    "formattedMasterAccount": "****4295",
                    "masterAccountName": "TEST FIRM",
                    "topicName": "Money Movement",
                    "subTopicName": "Other",
                    "description": "Test",
                    "createdDate": "2026-04-16T12:07:33Z",
                    "creator": "test_user",
                    "statusId": "1",
                    "hasAttachments": False,
                },
            }
        }
        resp = ServiceRequestCreateResponse.from_dict(data)
        assert resp.id == "SR378912733804863"
        assert resp.topic_name == "Money Movement"
        assert resp.creator == "test_user"

    def test_from_dict_empty(self):
        resp = ServiceRequestCreateResponse.from_dict({})
        assert resp.id == ""


# --- Status ---


class TestStatusEvent:
    def test_from_dict_with_attributes(self):
        data = {
            "id": "26068466-uuid",
            "type": "status-event",
            "attributes": {
                "statusObjectId": "b4e59d5c-uuid",
                "status": "New",
                "currentStatus": "Draft - Not ready",
                "currentStatusMessageDetail": "Draft detail",
                "createdDate": "2026-04-16T05:14:25Z",
                "assignmentGroup": "Advisor",
                "source": "AD00007188",
                "sourceUser": "Docupace Enterprise",
            },
        }
        evt = StatusEvent.from_dict(data)
        assert evt.id == "26068466-uuid"
        assert evt.status == "New"
        assert evt.current_status == "Draft - Not ready"
        assert evt.assignment_group == "Advisor"

    def test_from_dict_empty(self):
        evt = StatusEvent.from_dict({})
        assert evt.id == ""
        assert evt.status == ""

    def test_from_dict_parses_full_spec(self):
        """The OpenAPI defines 14 attribute fields; verify every one
        parses to a typed attribute (no silent drops)."""
        data = {
            "id": "evt-1",
            "type": "status-event",
            "attributes": {
                "statusObjectId": "obj-1",
                "status": "InProgress",
                "currentStatus": "Awaiting Documents",
                "currentStatusMessageDetail": "Need DL",
                "createdDate": "2026-04-16T05:14:25Z",
                "lastUpdatedDate": "2026-04-17T05:14:25Z",
                "estimatedCompletionDate": "2026-04-20",
                "assignmentGroup": "Advisor",
                "source": "AD00007188",
                "sourceId": "src-1",
                "sourceUser": "Docupace Enterprise",
                "canBeDeleted": True,
                "statusEventInfo": [{"key": "k", "value": "v"}],
                "upsTrackingInfo": [{"trackingNumber": "1Z999"}],
            },
        }
        evt = StatusEvent.from_dict(data)
        assert evt.id == "evt-1"
        assert evt.status_object_id == "obj-1"
        assert evt.estimated_completion_date == "2026-04-20"
        assert evt.can_be_deleted is True
        assert evt.status_event_info == [{"key": "k", "value": "v"}]
        assert evt.ups_tracking_info == [{"trackingNumber": "1Z999"}]


class TestStatusObject:
    def test_from_dict_from_feed_response(self):
        data = {
            "id": "b4e59d5c-uuid",
            "type": "status-object",
            "attributes": {
                "bundleId": "f595c897-uuid",
                "category": "Digital Envelope",
                "subCategory": "Account Open",
                "formattedMasterAccount": "***4295",
                "title": "AC Account Open",
                "description": "Action Center envelope",
                "isUpdatable": False,
                "statusEvents": [
                    {"id": "evt-1", "type": "status-event",
                     "attributes": {"status": "New"}},
                ],
            },
        }
        obj = StatusObject.from_dict(data)
        assert obj.status_object_id == "b4e59d5c-uuid"
        assert obj.category == "Digital Envelope"
        assert obj.title == "AC Account Open"
        assert len(obj.status_events) == 1
        assert obj.status_events[0].status == "New"

    def test_from_dict_inline(self):
        """Status objects from POST /status-feed are inline (no id/type wrapper)."""
        data = {
            "statusObjectId": "abc-123",
            "category": "Service Request",
            "title": "SR Title",
            "statusEvents": [],
        }
        obj = StatusObject.from_dict(data)
        assert obj.status_object_id == "abc-123"
        assert obj.category == "Service Request"

    def test_from_dict_full_account_metadata(self):
        """Schwab returns ~24 fields per status object; verify the expanded
        ones land on the dataclass (account name, formatted account,
        registration, entryChannel/source, tags, etc.)."""
        data = {
            "statusObjectId": "obj-x",
            "category": "Account Maintenance",
            "subCategory": "Account Update",
            "title": "Account Update",
            "description": "AS Account Maintenance",
            "formattedMasterAccount": "***4321",
            "formattedAccount": "****6789",
            "accountName": "A SAMPLE & B SAMPLE TTEE",
            "accountRegistrationType": "Liv Trust",
            "accountRegistrationDetails":
                "THE ALEX Q. SAMPLE REV TR U/A DTD 01/02/2003",
            "entryChannel": {"channel": "Advisor DocuSign", "tags": []},
            "clientInfo": {"profileType": "ADV", "auxProfileId": "87654321"},
            "confidentialInfo": [
                {"confidentialDecisionSystem": "branchCode",
                 "confidentialDecisionValue": "PB"},
            ],
            "tags": ["Account Maintenance"],
            "myqCaseId": "WI-12345",
            "actionCenterEnvelopeId": "e78bbe7d-x",
            "sourceUser": "esign@example.com",
            "closedDate": "2026-05-07T09:12:58.622",
            "statusEvents": [],
        }
        obj = StatusObject.from_dict(data)
        assert obj.formatted_account == "****6789"
        assert obj.account_name == "A SAMPLE & B SAMPLE TTEE"
        assert obj.account_registration_type == "Liv Trust"
        assert (
            obj.account_registration_details
            == "THE ALEX Q. SAMPLE REV TR U/A DTD 01/02/2003"
        )
        # Now typed: entry_channel → StatusEntryChannel,
        # client_info → StatusClientInfo,
        # confidential_info[i] → StatusConfidentialInfo.
        assert obj.entry_channel.channel == "Advisor DocuSign"
        assert obj.entry_channel.tags == []
        assert obj.client_info.profile_type == "ADV"
        assert obj.client_info.aux_profile_id == "87654321"
        assert obj.tags == ["Account Maintenance"]
        assert obj.myq_case_id == "WI-12345"
        assert obj.action_center_envelope_id == "e78bbe7d-x"
        assert obj.source_user == "esign@example.com"
        assert obj.closed_date == "2026-05-07T09:12:58.622"
        assert (
            obj.confidential_info[0].confidential_decision_value == "PB"
        )


class TestStatusFeedCreateResponse:
    def test_from_dict(self):
        data = {
            "data": {
                "id": "feed-uuid",
                "type": "status-feed",
                "attributes": {
                    "statusObjects": [
                        {"statusObjectId": "obj-1", "category": "Envelope",
                         "title": "Test", "statusEvents": []},
                    ]
                },
            }
        }
        resp = StatusFeedCreateResponse.from_dict(data)
        assert resp.feed_id == "feed-uuid"
        assert len(resp.status_objects) == 1
        assert resp.status_objects[0].status_object_id == "obj-1"


class TestStatusFeedResponse:
    def test_from_dict_list(self):
        data = {
            "data": [
                {"id": "obj-1", "type": "status-object",
                 "attributes": {"category": "Envelope", "title": "T",
                                "statusEvents": []}},
            ],
            "meta": {"paging": {"nextCursor": "c1"}, "count": {"actual": 1}},
        }
        resp = StatusFeedResponse.from_dict(data)
        assert len(resp.status_objects) == 1
        assert resp.status_objects[0].status_object_id == "obj-1"
        assert resp.next_cursor == "c1"

    def test_from_dict_empty(self):
        resp = StatusFeedResponse.from_dict({})
        assert resp.status_objects == []


class TestStatusEventsResponse:
    def test_from_dict(self):
        data = {
            "data": [
                {"id": "evt-1", "type": "status-event",
                 "attributes": {"status": "New", "currentStatus": "Draft"}},
            ]
        }
        resp = StatusEventsResponse.from_dict(data)
        assert len(resp.events) == 1
        assert resp.events[0].status == "New"


class TestStatusEventsPostResponse:
    def test_from_dict(self):
        data = {"data": {"id": "batch-1"}}
        resp = StatusEventsPostResponse.from_dict(data)
        assert resp.raw_data == data


# --- Pagination helper ---


class TestParseMeta:
    def test_with_cursor_and_total(self):
        # When includeTotalCount=true is sent, Schwab populates count.total.
        # That's the grand total — what response.total_count should reflect.
        data = {"meta": {"paging": {"nextCursor": "101"}, "count": {"total": 84, "actual": 50}}}
        cursor, count = _parse_meta(data)
        assert cursor == "101"
        assert count == 84

    def test_actual_alone_returns_none(self):
        # count.actual is the per-page count, not the grand total. When
        # the caller did NOT request includeTotalCount, only `actual` is
        # present and total_count must be None (not the page size).
        data = {"meta": {"paging": {"nextCursor": "101"}, "count": {"actual": 50}}}
        cursor, count = _parse_meta(data)
        assert cursor == "101"
        assert count is None

    def test_empty_meta(self):
        cursor, count = _parse_meta({})
        assert cursor is None
        assert count is None

    def test_partial_meta(self):
        cursor, count = _parse_meta({"meta": {"paging": {}}})
        assert cursor is None
        assert count is None


# --- Address ---


class TestAddress:
    def test_from_dict(self):
        data = {
            "addressLine1": "123 Main St",
            "addressLine2": "Suite 400",
            "city": "Philadelphia",
            "state": "PA",
            "zipCode": "19103",
            "country": "US",
        }
        addr = Address.from_dict(data)
        assert addr.address_line1 == "123 Main St"
        assert addr.city == "Philadelphia"
        assert addr.zip_code == "19103"

    def test_from_dict_empty(self):
        addr = Address.from_dict({})
        assert addr.address_line1 == ""
        assert addr.country == ""


# --- Account Profile ---


class TestAccountProfile:
    def test_from_dict_with_address(self):
        data = {
            "id": "prof-1",
            "type": "account-profile",
            "attributes": {
                "formattedAccount": "1234-5678",
                "formattedMasterAccount": "MASTER-1",
                "accountRegistrationType": "Individual",
                "accountTitle1": "John Doe",
                "emailAddress": "john@example.com",
                "mailingAddress": {
                    "addressLine1": "123 Main",
                    "city": "Philly",
                    "state": "PA",
                    "zipCode": "19103",
                },
                "isMoneyLinkEnabled": True,
                "restrictionCodes": ["R1", "R2"],
            },
        }
        prof = AccountProfile.from_dict(data)
        assert prof.formatted_account == "1234-5678"
        assert prof.registration_type == "Individual"
        assert prof.title1 == "John Doe"
        assert prof.email == "john@example.com"
        assert prof.mailing_address is not None
        assert prof.mailing_address.city == "Philly"
        assert prof.is_money_link_enabled is True
        assert prof.restriction_codes == ["R1", "R2"]

    def test_from_dict_without_address(self):
        data = {"attributes": {"formattedAccount": "1234"}}
        prof = AccountProfile.from_dict(data)
        assert prof.formatted_account == "1234"
        assert prof.mailing_address is None

    def test_from_dict_empty(self):
        prof = AccountProfile.from_dict({})
        assert prof.formatted_account == ""
        assert prof.restriction_codes == []


class TestAccountProfilesResponse:
    def test_from_dict(self):
        data = {
            "data": [
                {"attributes": {"formattedAccount": "1234"}},
                {"attributes": {"formattedAccount": "5678"}},
            ],
            "meta": {"paging": {"nextCursor": "next"}, "count": {"total": 12, "actual": 2}},
        }
        resp = AccountProfilesResponse.from_dict(data)
        assert len(resp.profiles) == 2
        assert resp.next_cursor == "next"
        assert resp.total_count == 12

    def test_from_dict_empty(self):
        resp = AccountProfilesResponse.from_dict({"data": []})
        assert resp.profiles == []
        assert resp.next_cursor is None


# --- Transaction ---


class TestTransaction:
    def test_from_dict(self):
        data = {
            "id": "txn-1",
            "type": "transaction",
            "attributes": {
                "formattedAccount": "1234-5678",
                "typeCode": "FC",
                "action": "MoneyLink Transfer",
                "description": "Tfr PNC BANK",
                "tradeDate": "2026-04-10",
                "settleDate": "2026-04-12",
                "executedDate": "2026-04-10",
                "amount": 1500.50,
                "netAmount": 1500.50,
                "quantity": 10,
                "price": 150.05,
                "securityType": "Equity",
                "cusipNumber": "037833100",
                "isIntraday": False,
                "hasDetails": True,
            },
        }
        txn = Transaction.from_dict(data)
        assert txn.id == "txn-1"
        assert txn.type_code == "FC"
        assert txn.action == "MoneyLink Transfer"
        assert txn.amount == 1500.50
        assert txn.net_amount == 1500.50
        assert txn.quantity == 10.0
        assert txn.price == 150.05
        assert txn.has_details is True

    def test_from_dict_empty(self):
        txn = Transaction.from_dict({})
        assert txn.amount == 0.0
        assert txn.quantity == 0.0
        assert txn.is_intraday is False

    def test_from_dict_numeric_amount(self):
        data = {"attributes": {"amount": 99.99, "quantity": 5}}
        txn = Transaction.from_dict(data)
        assert txn.amount == 99.99
        assert txn.quantity == 5.0


class TestTransactionsResponse:
    def test_from_dict(self):
        data = {
            "data": [{"id": "t1", "attributes": {"transactionType": "BUY"}}],
            "meta": {"paging": {"nextCursor": "c1"}, "count": {"actual": 1}},
        }
        resp = TransactionsResponse.from_dict(data)
        assert len(resp.transactions) == 1
        assert resp.next_cursor == "c1"

    def test_from_dict_empty(self):
        resp = TransactionsResponse.from_dict({"data": []})
        assert resp.transactions == []


# --- Standing Instruction ---


class TestStandingInstruction:
    """Verified against real sandbox data: the list endpoint returns
    summary records with `instructions: {nickname, transactionType,
    direction, hasIaAuthority}` nested under attributes — NOT the
    `instructionType`/`status`/`counterParty` shape we used to assume.
    Counter-party data is detail-endpoint only."""

    def test_summary_from_list_endpoint(self):
        # Real shape from /standing-instructions sandbox response.
        data = {
            "id": "J-1293876388-2022",
            "type": "standing-instruction-summary",
            "attributes": {
                "masterAccount": 8174295,
                "account": 14217596,
                "instructions": {
                    "nickname": "",
                    "transactionType": "J",
                    "direction": "Outgoing",
                    "hasIaAuthority": True,
                },
            },
        }
        si = StandingInstruction.from_dict(data)
        assert si.id == "J-1293876388-2022"
        assert si.master_account == "8174295"
        assert si.account == "14217596"
        assert si.transaction_type == "J"
        assert si.direction == "Outgoing"
        assert si.has_ia_authority is True

    def test_from_dict_empty(self):
        si = StandingInstruction.from_dict({})
        assert si.id == ""
        assert si.master_account == ""
        assert si.has_ia_authority is False


class TestStandingInstructionDetail:
    """The /standing-instructions/{id} endpoint returns
    `standing-instruction-detail` with the embedded counter-party
    object — bank routing, account, name, address, phone."""

    def test_full_detail_parse(self):
        # Real shape from /standing-instructions/{id} sandbox response.
        data = {
            "data": {
                "id": "J-1293876388-2022",
                "type": "standing-instruction-detail",
                "attributes": {
                    "masterAccount": 8174295,
                    "account": 14217596,
                    "instructions": {
                        "nickname": "Primary checking",
                        "transactionType": "A",
                        "direction": "Outgoing",
                        "counterParty": {
                            "routingNumber": "021000021",
                            "accountNumber": "9999999",
                            "name": "ACME LLC",
                            "bankName": "JPMORGAN",
                            "phone": "212-555-1212",
                            "address": {
                                "address1": "100 Main St",
                                "address2": "Suite 200",
                                "address3": "NEW YORK NY 10001 US",
                                "countryCode": "USA",
                            },
                        },
                        "hasIaAuthority": True,
                    },
                },
            },
        }
        d = StandingInstructionDetail.from_dict(data)
        assert d.id == "J-1293876388-2022"
        assert d.master_account == "8174295"
        assert d.account == "14217596"
        assert d.nickname == "Primary checking"
        assert d.transaction_type == "A"
        assert d.direction == "Outgoing"
        assert d.has_ia_authority is True
        cp = d.counter_party
        assert cp is not None
        assert cp.routing_number == "021000021"
        assert cp.account_number == "9999999"
        assert cp.name == "ACME LLC"
        assert cp.bank_name == "JPMORGAN"
        assert cp.phone == "212-555-1212"
        # Counter-party address has its own field names (address1,
        # address2, address3, countryCode) — different from regular Address.
        assert cp.address.address1 == "100 Main St"
        assert cp.address.address2 == "Suite 200"
        assert cp.address.address3 == "NEW YORK NY 10001 US"
        assert cp.address.country_code == "USA"

    def test_no_counter_party(self):
        # Detail with no counter-party (some SLOAs don't have it populated).
        data = {
            "data": {
                "id": "X-1",
                "attributes": {
                    "masterAccount": 1, "account": 2,
                    "instructions": {
                        "transactionType": "J", "direction": "Outgoing",
                        "hasIaAuthority": False,
                    },
                },
            },
        }
        d = StandingInstructionDetail.from_dict(data)
        assert d.counter_party is None
        assert d.transaction_type == "J"


class TestPreferencesAndAuthorizationsExpanded:
    """Verify the 3 nested objects parse into typed sub-dataclasses
    (catches the under-parsing regression we hit at 2/4 fields)."""

    def test_full_nested_parse(self):
        data = {
            "attributes": {
                "formattedAccount": "1234",
                "accountPreferences": {
                    "isPrimeBrokerEnabled": False,
                    "isMarginEnabled": True,
                    "enrolledInSchwabBillPay": False,
                    "cashSweepFund": "Schwab Bank Savings Sweep",
                    "isMoneyLinkEnabled": True,
                    "approvedOptionsLevel": "2",
                    "isClientCheckWritingEnabled": False,
                    "demandDepositAccount": "",
                    "allianceWebView": "FullView",
                },
                "cashAndMarginPreferences": {
                    "interestDividendsCashFrequency": "Hold",
                    "proceedsCashFrequency": "Hold",
                    "interestDividendsMarginFrequency": "Hold",
                    "proceedsMarginFrequency": "Hold",
                },
                "authorizations": {
                    "isTradingAuthorizationEnabled": True,
                    "disbursementAuthorization": "Limited",
                    "isFeePaymentAuthorizationEnabled": True,
                    "restrictionCodes": "TR-12,AD-3",
                },
            },
        }
        pa = PreferencesAndAuthorizations.from_dict(data)
        assert pa.formatted_account == "1234"
        assert pa.account_preferences.is_margin_enabled is True
        assert pa.account_preferences.is_money_link_enabled is True
        assert pa.account_preferences.approved_options_level == "2"
        assert pa.account_preferences.cash_sweep_fund == "Schwab Bank Savings Sweep"
        assert pa.cash_and_margin_preferences.proceeds_cash_frequency == "Hold"
        assert pa.authorizations.is_trading_authorization_enabled is True
        assert pa.authorizations.restriction_codes == "TR-12,AD-3"

    def test_missing_nested_objects_default_to_none(self):
        pa = PreferencesAndAuthorizations.from_dict({"attributes": {}})
        assert pa.account_preferences is None
        assert pa.cash_and_margin_preferences is None
        assert pa.authorizations is None


class TestAccountHolderExpanded:
    """All 17 documented holder fields parse, and Employment is typed."""

    def test_full_field_parse(self):
        data = {
            "attributes": {
                "role": "PrimaryAccountHolder",
                "name": "JOHN A SMITH",
                "formattedAccount": "10001015",
                "firstName": "JOHN",
                "middleName": "A",
                "lastName": "SMITH",
                "formattedDateOfBirth": "1960-01-15",
                "formattedTaxpayerId": "***-**-1234",
                "emailAddress": "j@example.com",
                "homePhone": "555-1111",
                "mobilePhone": "555-2222",
                "businessPhone": "555-3333",
                "citizenship": "US",
                "countryOfResidence": "US",
                "allianceWebAccess": "Enabled",
                "allianceInvitationDate": "2020-01-01",
                "mobileAccess": "Yes",
                "isTrustAccount": False,
                "employment": {
                    "employmentStatus": "EMPLOYED",
                    "employerName": "ACME CORP",
                    "occupation": "Engineer",
                    "industry": "Technology",
                    "yearsEmployed": "10",
                },
                "accounts": [{"formattedAccount": "10001015", "role": "PrimaryAccountHolder"}],
                "mailingAddress": {
                    "addressLine1": "1 Main St", "city": "BOS", "state": "MA",
                    "zipCode": "02101", "country": "US",
                },
            },
        }
        h = AccountHolder.from_dict(data)
        assert h.role == "PrimaryAccountHolder"
        assert h.name == "JOHN A SMITH"
        assert h.first_name == "JOHN"
        assert h.last_name == "SMITH"
        assert h.email_address == "j@example.com"
        assert h.home_phone == "555-1111"
        assert h.mobile_phone == "555-2222"
        assert h.business_phone == "555-3333"
        assert h.citizenship == "US"
        assert h.country_of_residence == "US"
        assert h.alliance_web_access == "Enabled"
        assert h.mobile_access == "Yes"
        assert h.is_trust_account is False
        assert h.employment is not None
        assert h.employment.employment_status == "EMPLOYED"
        assert h.employment.employer_name == "ACME CORP"
        assert h.employment.occupation == "Engineer"
        assert h.mailing_address.city == "BOS"
        assert h.mailing_address.state == "MA"
        assert len(h.accounts) == 1


class TestRoleExpanded:
    """Role inside AccountRole.roles is now typed (was a raw dict).
    Beneficiary fields, names, contact info, citizenship, alliance
    enrollment all parse to typed attributes."""

    def test_beneficiary_role_full_parse(self):
        from schwab_advisor.models import AccountRole, Role
        data = {
            "id": "10001015",
            "type": "account-role",
            "attributes": {
                "formattedAccount": "10001015",
                "formattedMasterAccount": "8174295",
                "roles": [
                    {
                        "accountHolderId": "ah-1",
                        "accountHolderType": "Individual",
                        "role": "PrimaryAccountHolder",
                        "isPrimaryContact": True,
                        "firstName": "JOHN",
                        "lastName": "SMITH",
                        "emailAddress": "j@example.com",
                        "citizenship1": "US",
                        "isAccountWebEnabled": True,
                        "isLoginIdEnrolled": True,
                        "loginIdEnrollStatus": "Enrolled",
                    },
                    {
                        "accountHolderId": "ah-2",
                        "accountHolderType": "Individual",
                        "role": "Beneficiary",
                        "beneficiaryRelationship": "Spouse",
                        "beneficiaryAssetPercentage": "50",
                        "beneficiaryAssetFraction": 0.5,
                        "firstName": "JANE",
                        "lastName": "SMITH",
                    },
                ],
            },
        }
        ar = AccountRole.from_dict(data)
        assert ar.formatted_account == "10001015"
        assert ar.formatted_master_account == "8174295"
        assert len(ar.roles) == 2
        primary, beneficiary = ar.roles
        # Primary holder fields
        assert primary.account_holder_id == "ah-1"
        assert primary.role == "PrimaryAccountHolder"
        assert primary.is_primary_contact is True
        assert primary.first_name == "JOHN"
        assert primary.last_name == "SMITH"
        assert primary.email_address == "j@example.com"
        assert primary.citizenship1 == "US"
        assert primary.is_account_web_enabled is True
        assert primary.login_id_enroll_status == "Enrolled"
        # Beneficiary-specific fields
        assert beneficiary.role == "Beneficiary"
        assert beneficiary.beneficiary_relationship == "Spouse"
        assert beneficiary.beneficiary_asset_percentage == "50"
        assert beneficiary.beneficiary_asset_fraction == 0.5
        assert beneficiary.first_name == "JANE"


class TestAddressExpanded:
    """Address has 9 fields including addressLine3, addressType, isInternational."""

    def test_full_field_parse(self):
        a = Address.from_dict({
            "addressLine1": "10 Downing St",
            "addressLine2": "Apt 7",
            "addressLine3": "Floor 3",
            "city": "London", "state": "", "zipCode": "SW1A 2AA",
            "country": "UK", "addressType": "Mailing", "isInternational": True,
        })
        assert a.address_line1 == "10 Downing St"
        assert a.address_line2 == "Apt 7"
        assert a.address_line3 == "Floor 3"
        assert a.address_type == "Mailing"
        assert a.is_international is True

    def test_minimal_defaults(self):
        a = Address.from_dict({})
        assert a.address_line3 == ""
        assert a.is_international is False


class TestStandingInstructionsResponse:
    def test_from_dict(self):
        data = {
            "data": [{"id": "si-1", "attributes": {"instructionType": "ACH"}}],
            "meta": {"paging": {}, "count": {"actual": 1}},
        }
        resp = StandingInstructionsResponse.from_dict(data)
        assert len(resp.instructions) == 1


# --- Account Holder ---


class TestAccountHolder:
    def test_from_dict_with_address(self):
        data = {
            "attributes": {
                "formattedAccount": "1234",
                "firstName": "John",
                "middleName": "Q",
                "lastName": "Doe",
                "formattedDateOfBirth": "01/15/1980",
                "mailingAddress": {"addressLine1": "123 Main", "city": "Philly"},
            },
        }
        holder = AccountHolder.from_dict(data)
        assert holder.first_name == "John"
        assert holder.last_name == "Doe"
        assert holder.date_of_birth == "01/15/1980"
        assert holder.mailing_address is not None
        assert holder.mailing_address.city == "Philly"

    def test_from_dict_without_address(self):
        holder = AccountHolder.from_dict({"attributes": {"firstName": "Jane"}})
        assert holder.first_name == "Jane"
        assert holder.mailing_address is None


class TestAccountHoldersResponse:
    def test_from_dict(self):
        data = {
            "data": [{"attributes": {"firstName": "John"}}],
            "meta": {"paging": {"nextCursor": "c2"}, "count": {"actual": 1}},
        }
        resp = AccountHoldersResponse.from_dict(data)
        assert len(resp.holders) == 1
        assert resp.next_cursor == "c2"


# --- Preferences and Authorizations ---


class TestPreferencesAndAuthorizations:
    def test_from_dict(self):
        data = {
            "attributes": {"formattedAccount": "1234"},
        }
        pref = PreferencesAndAuthorizations.from_dict(data)
        assert pref.formatted_account == "1234"
        assert pref.raw_data == data


class TestPreferencesAndAuthorizationsResponse:
    def test_from_dict(self):
        data = {"data": [{"attributes": {"formattedAccount": "1234"}}]}
        resp = PreferencesAndAuthorizationsResponse.from_dict(data)
        assert len(resp.items) == 1

    def test_from_dict_empty(self):
        resp = PreferencesAndAuthorizationsResponse.from_dict({"data": []})
        assert resp.items == []


# --- Edge cases: StatusFeedResponse dict vs list ---


class TestStatusFeedResponseEdgeCases:
    def test_from_dict_single_dict(self):
        data = {
            "data": {"id": "obj-1", "attributes": {"category": "Test", "statusEvents": []}},
        }
        resp = StatusFeedResponse.from_dict(data)
        assert len(resp.status_objects) == 1
        assert resp.status_objects[0].status_object_id == "obj-1"

    def test_from_dict_null_data(self):
        resp = StatusFeedResponse.from_dict({"data": None})
        assert resp.status_objects == []


# --- Edge cases: typed methods that previously returned dict ---


class TestOrderStatusDetailNumericCoercion:
    """OrderStatusDetail tolerates string/None numeric fields the wire
    sometimes returns for absent prices on validation-only orders."""

    def test_string_numeric_coerced(self):
        d = OrderStatusDetail.from_dict({
            "advisorId": "AD1", "orderNumber": "100",
            "quantity": "10", "actualPrice": "175.5",
            "limitPrice": "", "stopPrice": None,
        })
        assert d.quantity == 10.0
        assert d.actual_price == 175.5
        # Empty string and None defaulted to 0.0 (not exception).
        assert d.limit_price == 0.0
        assert d.stop_price == 0.0

    def test_invalid_numeric_falls_back(self):
        d = OrderStatusDetail.from_dict({"quantity": "not a number"})
        assert d.quantity == 0.0


class TestOrdersResponseEdgeCases:
    def test_empty_order_results(self):
        resp = OrdersResponse.from_dict({
            "data": {"id": "x", "type": "submit-order-response",
                     "attributes": {"totalCount": 0, "successfulCount": 0,
                                    "fatalErrorCount": 0,
                                    "informationalCount": 0,
                                    "orderResults": []}},
        })
        assert resp.total_count == 0
        assert resp.order_results == []

    def test_missing_data_wrapper(self):
        # Empty dict shouldn't blow up — defaults should kick in.
        resp = OrdersResponse.from_dict({})
        assert resp.total_count == 0
        assert resp.order_results == []
        assert resp.id == ""


class TestOrdersStatusResponseEdgeCases:
    def test_one_asset_class_only(self):
        # Real responses often have either equity OR mutual_fund details,
        # not both. Verify the missing-array case defaults to empty list.
        resp = OrdersStatusResponse.from_dict({
            "data": {"id": "x", "type": "order-status-response",
                     "attributes": {
                         "totalOrders": 1,
                         "equityOrderStatusDetails": [
                             {"orderNumber": "100", "status": "Filled",
                              "symbol": "AAPL", "quantity": 10},
                         ],
                     }},
        })
        assert resp.total_orders == 1
        assert len(resp.equity_order_status_details) == 1
        assert resp.mutual_fund_order_status_details == []
        assert resp.validation_errors == []

    def test_missing_data(self):
        resp = OrdersStatusResponse.from_dict({})
        assert resp.total_orders == 0
        assert resp.equity_order_status_details == []
        assert resp.mutual_fund_order_status_details == []


class TestUserAuthorizationsResponseEdgeCases:
    def test_empty_authorizations(self):
        resp = UserAuthorizationsResponse.from_dict({
            "data": {"id": "u-1", "type": "authorizations",
                     "attributes": {"isUserFsa": False,
                                    "authorizations": []}},
        })
        assert resp.is_user_fsa is False
        assert resp.authorizations == []

    def test_missing_attributes(self):
        # Defensive: server responds with bare data wrapper.
        resp = UserAuthorizationsResponse.from_dict({
            "data": {"id": "u-1", "type": "authorizations"},
        })
        assert resp.id == "u-1"
        assert resp.authorizations == []


class TestDataDeliveryEnrollmentResponseEdgeCases:
    def test_enrolled_true(self):
        resp = DataDeliveryEnrollmentResponse.from_dict({
            "data": {"attributes": {"enrolled": True}},
        })
        assert resp.enrolled is True

    def test_missing_data(self):
        # Sandbox sometimes returns just `{}` for unprovisioned scope —
        # parser should default cleanly, not crash.
        resp = DataDeliveryEnrollmentResponse.from_dict({})
        assert resp.enrolled is False

    def test_enrolled_false(self):
        resp = DataDeliveryEnrollmentResponse.from_dict({
            "data": {"attributes": {"enrolled": False}},
        })
        assert resp.enrolled is False

    def test_enrolled_missing_in_attributes(self):
        # attributes present but no `enrolled` key → default False, no crash.
        resp = DataDeliveryEnrollmentResponse.from_dict({
            "data": {"id": "x", "type": "data-delivery-enrollment",
                     "attributes": {}},
        })
        assert resp.enrolled is False

    def test_raw_data_preserved(self):
        payload = {"data": {"attributes": {"enrolled": True}}}
        resp = DataDeliveryEnrollmentResponse.from_dict(payload)
        assert resp.raw_data == payload


class TestMoveMoneyActivitiesResponseEdgeCases:
    def test_full_parse(self):
        resp = MoveMoneyActivitiesResponse.from_dict({
            "data": {"id": "act-1", "type": "activities", "attributes": {
                "formattedAccount": "****1857",
                "recurring": [{"transactionId": "R1", "transactionType": "ACH",
                               "direction": "Incoming", "amount": 10.0,
                               "frequency": "MONTHLY", "status": "Active"}],
                "upcoming": [],
                "recent": [{"transactionId": "W1", "transactionType": "Wire",
                            "direction": "Outgoing", "amount": 60.2,
                            "transactionDate": "2026-07-08", "status": "Pending"}],
            }},
        })
        assert resp.formatted_account == "****1857"
        assert len(resp.recurring) == 1 and resp.recurring[0].frequency == "MONTHLY"
        assert resp.upcoming == []
        assert resp.recent[0].amount == 60.2
        assert isinstance(resp.recent[0], MoveMoneyActivity)

    def test_empty_buckets(self):
        # Account with no activity — all buckets default to [], no crash.
        resp = MoveMoneyActivitiesResponse.from_dict({
            "data": {"attributes": {"formattedAccount": "****0000"}},
        })
        assert resp.recurring == [] and resp.upcoming == [] and resp.recent == []

    def test_missing_data(self):
        resp = MoveMoneyActivitiesResponse.from_dict({})
        assert resp.formatted_account == ""
        assert resp.recent == []

    def test_activity_missing_optional_fields(self):
        # A sparse activity item shouldn't crash; missing amount defaults 0.0.
        a = MoveMoneyActivity.from_dict({"transactionId": "X1"})
        assert a.transaction_id == "X1"
        assert a.amount == 0.0
        assert a.direction == ""


class TestAddressChangeCreateResponseEdgeCases:
    def test_full_parse(self):
        resp = AddressChangeCreateResponse.from_dict({
            "data": {"id": "ac-1", "type": "address-change",
                     "attributes": {"envelopeId": "env-42"}},
        })
        assert resp.id == "ac-1"
        assert resp.envelope_id == "env-42"

    def test_missing_envelope_id(self):
        # Spec says envelopeId is optional in the response.
        resp = AddressChangeCreateResponse.from_dict({
            "data": {"id": "ac-1", "type": "address-change"},
        })
        assert resp.id == "ac-1"
        assert resp.envelope_id == ""


class TestAddressChangesResponseSingleVsList:
    """The /address-changes/{id} endpoint returns a SINGLE-OBJECT data;
    the list endpoint returns an ARRAY. Same JSON:API single-vs-list
    pattern as /profiles/account-holders. AddressChangesResponse must
    handle both shapes."""

    def test_list_shape(self):
        resp = AddressChangesResponse.from_dict({
            "data": [{"id": "ac-1", "attributes": {"actionStatus": "Pending"}}],
            "meta": {"count": {"total": 1}},
        })
        assert len(resp.changes) == 1
        assert resp.changes[0].action_status == "Pending"
        assert resp.total_count == 1

    def test_single_object_shape(self):
        # When called as /address-changes/{action_id}.
        resp = AddressChangesResponse.from_dict({
            "data": {"id": "ac-1", "attributes": {"actionStatus": "Completed"}},
        })
        assert len(resp.changes) == 1
        assert resp.changes[0].action_status == "Completed"

    def test_empty_list(self):
        resp = AddressChangesResponse.from_dict({"data": []})
        assert resp.changes == []


class TestAccountProfileExpanded:
    """Catches the audit gap: AccountProfile was 17/26; now should be
    26/26 with the prefs/sweep/options fields typed."""

    def test_full_field_parse(self):
        from schwab_advisor.models import AccountProfile
        data = {
            "id": "p1",
            "type": "account-profile",
            "attributes": {
                "formattedAccount": "10001857",
                "formattedMasterAccount": "8174295",
                "accountTitle1": "JOHN SMITH",
                "accountRegistrationType": "Individual",
                "isMoneyLinkEnabled": True,
                "isMarginEnabled": True,
                "approvedOptionsLevel": "2",
                "enrolledInSchwabBillPay": True,
                "isClientCheckWritingEnabled": False,
                "cashSweepFund": "Schwab Bank Savings Sweep",
                "interestDividendsCashFrequency": "Hold",
                "proceedsCashFrequency": "Hold",
                "interestDividendsMarginFrequency": "Reinvest",
                "proceedsMarginFrequency": "Hold",
                "isFeePaymentAuthorizationEnabled": True,
                "restrictionCodes": ["TR-12"],
                "documentDeliveryOptions": [{"docType": "STATEMENT"}],
            },
        }
        p = AccountProfile.from_dict(data)
        # All 9 previously-missing fields now parse:
        assert p.approved_options_level == "2"
        assert p.cash_sweep_fund == "Schwab Bank Savings Sweep"
        assert p.enrolled_in_schwab_bill_pay is True
        assert p.is_client_check_writing_enabled is False
        assert p.interest_dividends_cash_frequency == "Hold"
        assert p.proceeds_cash_frequency == "Hold"
        assert p.interest_dividends_margin_frequency == "Reinvest"
        assert p.proceeds_margin_frequency == "Hold"
        assert p.document_delivery_options == [{"docType": "STATEMENT"}]


class TestAccountRmdExpanded:
    """AccountRmd was 14/42; now parses all 42. Test the new fields:
    quarterly/monthly RMD amounts, distribution tracking,
    contribution tracking, tax withholding."""

    def test_full_field_parse(self):
        from schwab_advisor.models import AccountRmd
        data = {
            "id": "r1",
            "type": "account-rmd",
            "attributes": {
                "formattedAccount": "10006285",
                "formattedMasterAccount": "8174295",
                "masterAccountType": "FA",
                "accountRegistrationType": "Roth IRA",
                "isRothIra": True,
                "openedThisYear": False,
                "accountTitle1": "JANE",
                "accountTitle2": "DOE IRA",
                "accountTitle3": "",
                "firstName": "JANE",
                "middleName": "Q",
                "lastName": "DOE",
                "dateReachesFiftyNineAndHalf": "2030-06-15",
                "rmdRequiredBeginningDate": "2042-04-01",
                "rmdDueDate": "2026-12-31",
                "currentYear": 2026,
                "priorYear": 2025,
                "rmdCalculationMethod": "UniformLifetime",
                "lifeExpectancyFactor": 27.4,
                "priorYearEndValue": 100000.0,
                "rmdCurrentYear": 3650.0,
                "rmdCurrentQuarter": 912.5,
                "rmdCurrentMonth": 304.17,
                "rmdPriorYear": 3500.0,
                "rmdTwoYearsPrior": 3400.0,
                "yearToDateRmdDistributions": 1000.0,
                "priorYearRmdDistributions": 3500.0,
                "rmdDistributionsRemainingCurrentYear": 2650.0,
                "rmdDistributionsRemainingPriorYear": 0.0,
                "yearToDateContribution": 7000.0,
                "priorYearContributions": 7000.0,
                "rolloverContributionThisYear": 0.0,
                "rothConversionsYearToDate": 5000.0,
                "totalDistributionsYearToDate": 1000.0,
                "totalDistributionsPriorYear": 3500.0,
                "totalMinusRothConvYearToDate": -4000.0,
                "isTaxWithholdingElected": True,
                "isTaxWithholdingFederalOptedOut": False,
                "taxWithholdingElectionFederal": 10.0,
                "isTaxWithholdingStateOptedOut": False,
                "taxWithholdingElectionState": 5.0,
                "taxWithholdingStateCode": "MA",
            },
        }
        r = AccountRmd.from_dict(data)
        # Newly-typed fields:
        assert r.master_account_type == "FA"
        assert r.opened_this_year is False
        assert r.title2 == "DOE IRA"
        assert r.middle_name == "Q"
        assert r.date_reaches_fifty_nine_and_half == "2030-06-15"
        assert r.rmd_due_date == "2026-12-31"
        assert r.rmd_calculation_method == "UniformLifetime"
        assert r.rmd_current_quarter == 912.5
        assert r.rmd_current_month == 304.17
        assert r.rmd_two_years_prior == 3400.0
        assert r.year_to_date_rmd_distributions == 1000.0
        assert r.rmd_distributions_remaining_current_year == 2650.0
        assert r.year_to_date_contribution == 7000.0
        assert r.roth_conversions_year_to_date == 5000.0
        assert r.total_distributions_year_to_date == 1000.0
        assert r.total_minus_roth_conv_year_to_date == -4000.0
        assert r.is_tax_withholding_elected is True
        assert r.tax_withholding_election_federal == 10.0
        assert r.tax_withholding_election_state == 5.0
        assert r.tax_withholding_state_code == "MA"


class TestDocumentPreferenceTyped:
    """DocumentPreferencesResponse.document_preferences was list[dict];
    now list[DocumentPreference] with typed nested ReportPreferences,
    DeliveryPreferences, ManagedAccountInfo, CommunicationDetail."""

    def test_full_typed_parse(self):
        from schwab_advisor.models import DocumentPreferencesResponse
        data = {
            "data": {
                "type": "document-preferences",
                "attributes": {
                    "documentPreferences": [
                        {
                            "formattedAccount": "10001857",
                            "reportPreferences": {
                                "statementType": "Customizable",
                                "isStatementBundled": False,
                                "tradeConfirmationsFormat": "Detail",
                            },
                            "delivery": {
                                "enrollmentInstruction": "Not Sent",
                                "isStatementSuppressionEnabled": False,
                                "equityCommissionAmount": "0.00",
                                "legacySource": "AS",
                                "documentDeliveryOptions": [{"k": "v"}],
                                "duplicateStatements": [],
                                "duplicateTradeConfirmations": [],
                            },
                            "managedAccount": {
                                "platform": "Schwab",
                                "moneyManager": "Acme Capital",
                                "investmentStrategy": "Balanced 60/40",
                            },
                            "issuerCommunications": [
                                {"type": "Proxy", "original": "Y",
                                 "informationalCopy": "N",
                                 "lastUpdatedDate": "2026-01-01"},
                            ],
                        },
                    ],
                },
            },
        }
        resp = DocumentPreferencesResponse.from_dict(data)
        assert len(resp.document_preferences) == 1
        d = resp.document_preferences[0]
        assert d.formatted_account == "10001857"
        assert d.report_preferences.statement_type == "Customizable"
        assert d.report_preferences.trade_confirmations_format == "Detail"
        assert d.delivery.enrollment_instruction == "Not Sent"
        assert d.delivery.equity_commission_amount == "0.00"
        assert d.managed_account.money_manager == "Acme Capital"
        assert d.managed_account.investment_strategy == "Balanced 60/40"
        assert len(d.issuer_communications) == 1
        ic = d.issuer_communications[0]
        assert ic.type == "Proxy"
        assert ic.original == "Y"


class TestNewTypedStructsEmpty:
    """Defensive: every new typed struct must parse `{}` cleanly (all
    defaults, no AttributeError) and tolerate the parent giving `None`
    or missing keys for the nested object."""

    def test_report_preferences_empty(self):
        from schwab_advisor.models import ReportPreferences
        r = ReportPreferences.from_dict({})
        assert r.statement_type == ""
        assert r.is_statement_bundled is False
        assert r.trade_confirmations_format == ""

    def test_delivery_preferences_empty(self):
        from schwab_advisor.models import DeliveryPreferences
        d = DeliveryPreferences.from_dict({})
        assert d.enrollment_instruction == ""
        assert d.is_statement_suppression_enabled is False
        assert d.equity_commission_amount == ""
        assert d.legacy_source == ""
        assert d.document_delivery_options == []
        assert d.duplicate_statements == []
        assert d.duplicate_trade_confirmations == []

    def test_delivery_preferences_null_arrays(self):
        # Schwab sometimes sends null instead of [] for empty arrays.
        from schwab_advisor.models import DeliveryPreferences
        d = DeliveryPreferences.from_dict({
            "documentDeliveryOptions": None,
            "duplicateStatements": None,
            "duplicateTradeConfirmations": None,
        })
        assert d.document_delivery_options == []
        assert d.duplicate_statements == []
        assert d.duplicate_trade_confirmations == []

    def test_managed_account_empty(self):
        from schwab_advisor.models import ManagedAccountInfo
        m = ManagedAccountInfo.from_dict({})
        assert m.platform == ""
        assert m.money_manager == ""
        assert m.investment_strategy == ""

    def test_communication_detail_empty(self):
        from schwab_advisor.models import CommunicationDetail
        c = CommunicationDetail.from_dict({})
        assert c.type == ""

    def test_document_preference_with_no_nested(self):
        # Wire returns the account but nothing nested inside.
        from schwab_advisor.models import DocumentPreference
        d = DocumentPreference.from_dict({"formattedAccount": "10001857"})
        assert d.formatted_account == "10001857"
        assert d.report_preferences is None
        assert d.delivery is None
        assert d.managed_account is None
        assert d.issuer_communications == []

    def test_document_preferences_response_empty_data(self):
        from schwab_advisor.models import DocumentPreferencesResponse
        # data: null
        resp = DocumentPreferencesResponse.from_dict({"data": None})
        assert resp.document_preferences == []
        # No data key at all
        resp = DocumentPreferencesResponse.from_dict({})
        assert resp.document_preferences == []
        # Empty docPrefs array
        resp = DocumentPreferencesResponse.from_dict({
            "data": {"attributes": {"documentPreferences": []}},
        })
        assert resp.document_preferences == []
        # Null docPrefs (instead of [])
        resp = DocumentPreferencesResponse.from_dict({
            "data": {"attributes": {"documentPreferences": None}},
        })
        assert resp.document_preferences == []

    def test_status_entry_channel_empty(self):
        from schwab_advisor.models import StatusEntryChannel
        e = StatusEntryChannel.from_dict({})
        assert e.channel == ""
        assert e.tags == []

    def test_status_entry_channel_null_tags(self):
        from schwab_advisor.models import StatusEntryChannel
        e = StatusEntryChannel.from_dict({"channel": "X", "tags": None})
        assert e.tags == []

    def test_status_object_client_info_empty(self):
        from schwab_advisor.models import StatusClientInfo
        c = StatusClientInfo.from_dict({})
        assert c.profile_type == ""
        assert c.profile_id == ""
        assert c.formatted_account == ""
        assert c.aux_profile_id == ""

    def test_status_confidential_info_empty(self):
        from schwab_advisor.models import StatusConfidentialInfo
        c = StatusConfidentialInfo.from_dict({})
        assert c.confidential_decision_system == ""
        assert c.confidential_decision_value == ""

    def test_status_additional_info_empty(self):
        from schwab_advisor.models import StatusAdditionalInfo
        a = StatusAdditionalInfo.from_dict({})
        assert a.additional_info_id == ""
        assert a.can_be_deleted is False
        assert a.process_details == []

    def test_status_object_with_null_nested(self):
        # Wire returns the parent but null for nested struct keys.
        # The model should produce None for object fields and [] for
        # arrays, never raise.
        obj = StatusObject.from_dict({
            "attributes": {
                "category": "Account Update",
                "entryChannel": None,
                "clientInfo": None,
                "confidentialInfo": None,
                "statusObjectInfo": None,
            },
        })
        assert obj.entry_channel is None
        assert obj.client_info is None
        assert obj.confidential_info == []
        assert obj.status_object_info == []


class TestAccountProfileMissingFields:
    """The newly-added prefs fields must default cleanly when absent
    (Schwab doesn't always populate every field for every account)."""

    def test_minimal_payload(self):
        from schwab_advisor.models import AccountProfile
        p = AccountProfile.from_dict({"attributes": {}})
        assert p.approved_options_level == ""
        assert p.cash_sweep_fund == ""
        assert p.enrolled_in_schwab_bill_pay is False
        assert p.is_client_check_writing_enabled is False
        assert p.interest_dividends_cash_frequency == ""
        assert p.proceeds_cash_frequency == ""
        assert p.interest_dividends_margin_frequency == ""
        assert p.proceeds_margin_frequency == ""
        assert p.document_delivery_options == []


class TestAccountRmdMissingFields:
    """All 28 newly-added RMD fields must default cleanly when absent."""

    def test_minimal_payload(self):
        from schwab_advisor.models import AccountRmd
        r = AccountRmd.from_dict({"attributes": {}})
        # Numeric fields default to 0.0 (not exception) on missing input
        assert r.rmd_current_quarter == 0.0
        assert r.rmd_current_month == 0.0
        assert r.year_to_date_rmd_distributions == 0.0
        assert r.tax_withholding_election_federal == 0.0
        # String fields default to ""
        assert r.master_account_type == ""
        assert r.middle_name == ""
        assert r.rmd_calculation_method == ""
        assert r.tax_withholding_state_code == ""
        # Bool fields default to False
        assert r.opened_this_year is False
        assert r.is_tax_withholding_elected is False


@requires_specs
class TestSchemaCoverageRegressionGuard:
    """Meta-test: re-runs the (model, OpenAPI schema) audit as part of
    the CI suite. If anyone adds a model without covering its full
    spec field set, or removes a field from a model, this fails.

    Intentionally narrow — covers the seven bundle + alerts/status
    APIs the audit was scoped to. If a new API/model is added, add
    it to the EXPECTED_PAIRS list."""

    EXPECTED_PAIRS = [
        # (model, spec file, schema path within spec, max_missing)
        # max_missing > 0 only for known false-positives (audit limitations).
        ("AccountProfile", "schwab-account-openapi.json",
         "AccountProfilesGetResponseData/attributes", 0),
        ("AccountRole", "schwab-account-openapi.json",
         "AccountRolesGetResponseData/attributes", 0),
        ("Role", "schwab-account-openapi.json", "Roles", 0),
        ("AccountHolder", "schwab-profiles-openapi.json",
         "ProfilesAccountHoldersGetResponseDataAttributes", 0),
        ("CounterParty", "schwab-standing-authorizations-openapi.json",
         "CounterParty", 0),
        ("CounterPartyAddress", "schwab-standing-authorizations-openapi.json",
         "Address", 0),
        ("AccountPreferences",
         "schwab-accounts-preferences-and-authorizations-openapi.json",
         "AccountPreferences", 0),
        ("Authorizations",
         "schwab-accounts-preferences-and-authorizations-openapi.json",
         "Authorizations", 0),
        ("CashAndMarginPreferences",
         "schwab-accounts-preferences-and-authorizations-openapi.json",
         "CashAndMarginPreferences", 0),
        ("StatusHistoryEntry", "schwab-alerts-openapi.json", "StatusHistory", 0),
        ("ArchiveDetail", "schwab-alerts-openapi.json", "ArchiveDetail", 0),
        ("StatusEntryChannel", "schwab-status-openapi.json", "EntryChannel", 0),
        ("StatusClientInfo", "schwab-status-openapi.json", "ClientInfo", 0),
        ("StatusConfidentialInfo", "schwab-status-openapi.json",
         "ConfidentialInfo", 0),
        ("StatusAdditionalInfo", "schwab-status-openapi.json",
         "AdditionalInfo", 0),
        ("ReportPreferences", "schwab-document-preferences-openapi.json",
         "ReportPreferences", 0),
        ("DeliveryPreferences", "schwab-document-preferences-openapi.json",
         "Delivery", 0),
        ("ManagedAccountInfo", "schwab-document-preferences-openapi.json",
         "ManagedAccount", 0),
        ("CommunicationDetail", "schwab-document-preferences-openapi.json",
         "CommunicationDetail", 0),
        ("DocumentPreference", "schwab-document-preferences-openapi.json",
         "DocumentPreferences", 0),
        ("MoveMoneyActivity", "schwab-move-money-activity-openapi.json",
         "Recurring", 0),
        ("MoveMoneyActivity", "schwab-move-money-activity-openapi.json",
         "Upcoming", 0),
        ("TaxWithholdingElectionsResponse",
         "schwab-move-money-activity-openapi.json",
         "TaxWithholdingElectionsGetResponseDataAttributes", 0),
        ("AchTransferResponse", "schwab-move-money-transfers-openapi.json",
         "AchStandingAuthorizationsPostResponseDataAttributes", 0),
        ("WireTransferResponse", "schwab-move-money-transfers-openapi.json",
         "WiresTransferPostResponseAttributes", 0),
        ("RetirementDetails", "schwab-move-money-transfers-openapi.json",
         "RetirementResponseDetails", 0),
        ("ToFromAccount", "schwab-move-money-transfers-openapi.json",
         "ToFromAccount", 0),
        ("TransferWarning", "schwab-move-money-transfers-openapi.json",
         "Warning", 0),
        ("MoveMoneyActivity", "schwab-move-money-activity-openapi.json",
         "Recent", 0),
        # The six products enabled in prod 2026-07 — typed in v0.3.0.
        ("BalanceDetail", "schwab-balances-openapi.json",
         "BalancesDetailGetResponseDataAttributes", 0),
        ("Balance", "schwab-balances-openapi.json", "Balance", 0),
        ("TotalBalances", "schwab-balances-openapi.json", "TotalBalance", 0),
        ("BalanceListResponse", "schwab-balances-openapi.json",
         "BalancesListPostResponseDataAttributes", 0),
        ("Position", "schwab-positions-openapi.json", "Position", 0),
        ("ListPosition", "schwab-positions-openapi.json", "ListPosition", 0),
        ("TotalPositions", "schwab-positions-openapi.json", "TotalPositions", 0),
        ("PositionDetailResponse", "schwab-positions-openapi.json",
         "PositionsDetailGetResponseDataAttributes", 0),
        ("PositionListResponse", "schwab-positions-openapi.json",
         "PositionsListPostResponseDataAttributes", 0),
        ("Transaction", "schwab-transactions-openapi.json",
         "TransactionAttributes", 0),
        ("CostBasisAccountPreference", "schwab-cost-basis-openapi.json",
         "AccountPreferencesDetail", 0),
        ("RglTransaction", "schwab-cost-basis-openapi.json", "RglTransaction", 0),
        ("RglTransactionLot", "schwab-cost-basis-openapi.json",
         "RglTransactionLot", 0),
        ("RglSummary", "schwab-cost-basis-openapi.json",
         "RglTransactionsSummary", 0),
        ("CostBasisRglResponse", "schwab-cost-basis-openapi.json",
         "RglTransactionsGetResponseDataAttributes", 0),
        ("UglPosition", "schwab-cost-basis-openapi.json", "UglPositionDetail", 0),
        ("UglPositionLot", "schwab-cost-basis-openapi.json", "UglPositionLot", 0),
        ("UglPositionWithLots", "schwab-cost-basis-openapi.json", "UglPosition", 0),
        ("UglSummary", "schwab-cost-basis-openapi.json",
         "UglPositionsSummary", 0),
        ("CostBasisUglResponse", "schwab-cost-basis-openapi.json",
         "UglPositionsGetResponseDataAttributes", 0),
        ("UglPositionLotsResponse", "schwab-cost-basis-openapi.json",
         "UglPositionLotsPostResponseDataAttributes", 0),
    ]

    @staticmethod
    @functools.cache
    def _load_models_src():
        import os
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return open(os.path.join(root, "src/schwab_advisor/models.py")).read()

    @classmethod
    def _resolve_schema(cls, spec_path, schema_path):
        # Shared resolver — same walk semantics as scripts/audit_models.py
        # and the prod drift checks in test_production_integration.py.
        from schwab_advisor._spec import spec_properties

        return set(spec_properties(spec_path, schema_path))

    @classmethod
    def _model_keys(cls, class_name):
        import re
        src = cls._load_models_src()
        m = re.search(rf"\nclass {class_name}[\(:].*?(?=\nclass |\Z)",
                      src, re.DOTALL)
        if not m:
            return set()
        body = m.group(0)
        keys = set(re.findall(
            r"\.get\(\s*['\"]([A-Za-z][A-Za-z0-9]*)['\"]", body))
        # Also catch _safe_float/_safe_int(<any-var>, "key") helper calls
        # (multi-line tolerant; first arg may be attrs, data, d, ...)
        keys |= set(re.findall(
            r"_safe_(?:float|int)\(\s*\w+\s*,\s*['\"]([A-Za-z][A-Za-z0-9]*)['\"]",
            body, re.DOTALL))
        # Only filter JSON:API-plumbing keys ("data" / "attributes"); leave
        # "id"/"type" alone because some inner schemas (CommunicationDetail)
        # use those as real field names.
        keys -= {"data", "attributes"}
        return keys

    def test_no_under_parsing(self):
        failures = []
        for model, fname, schema, max_missing in self.EXPECTED_PAIRS:
            spec_path = SPECS_DIR / fname
            spec_keys = self._resolve_schema(spec_path, schema)
            if not spec_keys:
                failures.append(
                    f"{model}: schema '{schema}' in {fname} resolved to empty")
                continue
            mod_keys = self._model_keys(model)
            missing = spec_keys - mod_keys
            if len(missing) > max_missing:
                failures.append(
                    f"{model} ← {schema}: missing {len(missing)} field(s) "
                    f"(allowed {max_missing}): {sorted(missing)}"
                )
        assert not failures, "Under-parsing detected:\n" + "\n".join(failures)


class TestStatusObjectTypedNested:
    """StatusObject's nested fields (entry_channel, client_info,
    confidential_info, status_object_info) are now typed dataclasses."""

    def test_all_nested_typed(self):
        data = {
            "id": "obj-1",
            "type": "status-object",
            "attributes": {
                "category": "Account Maintenance",
                "entryChannel": {"channel": "Advisor DocuSign", "tags": ["E-Sig"]},
                "clientInfo": {"profileType": "ADV", "profileId": "P1",
                               "formattedAccount": "10001857",
                               "auxProfileId": "AUX-1"},
                "confidentialInfo": [
                    {"confidentialDecisionSystem": "branchCode",
                     "confidentialDecisionValue": "PB"},
                ],
                "statusObjectInfo": [
                    {"additionalInfoId": "info-1",
                     "additionalInfoSystem": "Docupace",
                     "additionalInfoUri": "https://example.com/doc/1",
                     "additionalInfoType": "EnvelopeId",
                     "additionalInfoValue": "env-42",
                     "additionalInfoKey": "envelopeId",
                     "additionalInfoDescription": "DocuSign envelope",
                     "additionalInfoCategory": "Document",
                     "canBeDeleted": True,
                     "processDetails": [{"step": "Sign"}]},
                ],
            },
        }
        obj = StatusObject.from_dict(data)
        assert obj.entry_channel.channel == "Advisor DocuSign"
        assert obj.entry_channel.tags == ["E-Sig"]
        assert obj.client_info.profile_id == "P1"
        assert obj.client_info.aux_profile_id == "AUX-1"
        assert len(obj.confidential_info) == 1
        assert obj.confidential_info[0].confidential_decision_system == "branchCode"
        assert len(obj.status_object_info) == 1
        ai = obj.status_object_info[0]
        assert ai.additional_info_system == "Docupace"
        assert ai.additional_info_value == "env-42"
        assert ai.can_be_deleted is True
        assert ai.process_details == [{"step": "Sign"}]


class TestTransactionDetail:
    """GET /transactions/detail returns a SINGLE record (data: {...}) with a
    fee/tax breakdown — a different shape than the /transactions list."""

    def test_from_dict_full(self):
        from schwab_advisor.models import TransactionDetail
        detail = TransactionDetail.from_dict({
            "data": {"id": "abc", "type": "transaction-detail", "attributes": {
                "formattedAccount": "****1857",
                "description": "TEST",
                "amount": 120.56,
                "netAmount": 118.06,
                "commission": 1.25,
                "orderHandlingFee": 0.75,
                "withholdingTax": 0.5,
                "executedDate": "2024-06-20",
                "settleDate": "2024-06-21",
            }},
        })
        assert detail.id == "abc"
        assert detail.formatted_account == "****1857"
        assert detail.amount == 120.56
        assert detail.net_amount == 118.06
        assert detail.commission == 1.25
        assert detail.order_handling_fee == 0.75
        assert detail.withholding_tax == 0.5
        assert detail.executed_date == "2024-06-20"
        assert detail.settle_date == "2024-06-21"

    def test_from_dict_empty_attributes(self):
        # Defensive-empty-payload convention: absent fields fall back to
        # typed defaults instead of raising.
        from schwab_advisor.models import TransactionDetail
        detail = TransactionDetail.from_dict({"data": {"id": "x", "attributes": {}}})
        assert detail.id == "x"
        assert detail.amount == 0.0
        assert detail.formatted_account == ""
        assert detail.executed_date == ""


@requires_specs
class TestPortfolioFullPayloadParsing:
    """Every spec-declared field must actually REACH the dataclass.

    TestSchemaCoverageRegressionGuard and the audit script both work by
    grepping the model source for JSON key strings — they prove a key is
    mentioned, not that parsing it lands anywhere. This builds a payload
    containing every field the spec declares, runs it through from_dict,
    and fails if any attribute is still at its default: a runtime check
    of the same claim, and one that needs no live API.

    (model, spec file, schema, wrap-in-JSON:API-envelope, fields to skip)
    """

    _CB = "schwab-cost-basis-openapi.json"
    _MM = "schwab-move-money-activity-openapi.json"

    PAIRS = [
        ("BalanceDetail", "schwab-balances-openapi.json",
         ["BalancesDetailGetResponseDataAttributes"], True, set()),
        ("Balance", "schwab-balances-openapi.json", ["Balance"], False, set()),
        ("TotalBalances", "schwab-balances-openapi.json",
         ["TotalBalance"], False, set()),
        # cusip_number / order ids / event_id are SPEC DRIFT — fields prod
        # returns that the spec never declares, so a spec-built payload
        # cannot populate them. TestProdObservedShapes covers them instead.
        ("Position", "schwab-positions-openapi.json", ["Position"], False,
         {"cusip_number"}),
        ("ListPosition", "schwab-positions-openapi.json",
         ["ListPosition"], False, {"cusip_number"}),
        ("TotalPositions", "schwab-positions-openapi.json",
         ["TotalPositions"], False, set()),
        ("Transaction", "schwab-transactions-openapi.json",
         ["TransactionAttributes"], True, {"order_id", "schwab_order_id"}),
        ("CostBasisAccountPreference", _CB, ["AccountPreferencesDetail"],
         False, set()),
        ("RglTransaction", _CB, ["RglTransaction"], False, set()),
        ("RglTransactionLot", _CB, ["RglTransactionLot"], False, {"event_id"}),
        ("RglSummary", _CB, ["RglTransactionsSummary"], False, set()),
        ("UglPosition", _CB, ["UglPositionDetail"], False, set()),
        ("UglPositionLot", _CB, ["UglPositionLot"], False, {"event_id"}),
        ("UglPositionWithLots", _CB, ["UglPosition"], False, set()),
        ("UglSummary", _CB, ["UglPositionsSummary"], False, set()),
        # MoveMoneyActivity spans three bucket schemas; the union is what
        # a single record can carry (recurring items have
        # nextTransactionDate, upcoming/recent have transactionDate).
        ("MoveMoneyActivity", _MM, ["Recurring", "Upcoming", "Recent"],
         False, set()),
    ]

    @staticmethod
    def _spec_props(spec_file, schema):
        """Property name → JSON type for one component schema.

        Walks allOf composition (Recurring/Upcoming/Recent are built that
        way) and follows $ref hops, so the payload built from this covers
        inherited fields too — the same field set spec_properties()
        reports, with types attached.
        """
        import json
        doc = json.load(open(SPECS_DIR / spec_file))
        schemas = doc["components"]["schemas"]

        def resolve(node, seen=()):
            if not isinstance(node, dict):
                return {}
            ref = (node.get("$ref") or "").split("/")[-1]
            if ref:
                if ref in seen:
                    return {}
                return resolve(schemas.get(ref, {}), seen + (ref,))
            out = {}
            for branch in node.get("allOf") or []:
                out.update(resolve(branch, seen))
            for name, prop in (node.get("properties") or {}).items():
                target = prop
                pref = (prop.get("$ref") or "").split("/")[-1]
                if pref:
                    target = schemas.get(pref, {})
                out[name] = target.get("type")
            return out

        return resolve(schemas[schema])

    @staticmethod
    def _sentinel(json_type):
        return {
            "string": "x",
            "number": 1.5,
            "integer": 7,
            "boolean": True,
            # A generic record: enough keys that any typed item model
            # built from it parses to something non-empty.
            "array": [{"lotId": "x", "positionId": "x", "symbol": "x"}],
            "object": {"k": "v"},
        }.get(json_type, "x")

    def test_every_spec_field_reaches_the_model(self):
        import dataclasses

        import schwab_advisor.models as m

        failures = []
        for name, spec_file, schemas, wrap, skip in self.PAIRS:
            cls = getattr(m, name)
            payload = {}
            for schema in schemas:
                for prop, jtype in self._spec_props(spec_file, schema).items():
                    payload[prop] = self._sentinel(jtype)
            data = {"id": "x", "type": "t", "attributes": payload} if wrap else payload
            obj = cls.from_dict(data)
            defaulted = []
            for f in dataclasses.fields(cls):
                if f.name in ("raw_data",) or f.name in skip:
                    continue
                # Compare against the field's declared default rather than
                # falsiness — 0.0 and False are legitimate parsed values,
                # and treating them as "empty" is how under-parsing hides.
                if f.default is not dataclasses.MISSING:
                    default = f.default
                elif f.default_factory is not dataclasses.MISSING:
                    default = f.default_factory()
                else:
                    default = None
                if getattr(obj, f.name) == default:
                    defaulted.append(f.name)
            if defaulted:
                failures.append(f"{name}: fields never populated: {defaulted}")
        assert not failures, (
            "spec fields declared but not wired into the model:\n"
            + "\n".join(failures)
        )


class TestProdObservedShapes:
    """Payload shapes taken from the 2026-07-28 production run.

    Values are synthetic; the SHAPES are real. Each case pins something
    prod does that the OpenAPI specs do not describe — the class exists
    because every one of these was invisible to spec-derived tests.
    """

    def test_preferences_response_wrapper_shape(self):
        """Prod (and the spec) return ONE data object with a nested
        `preferencesAndAuthorizations` list; sandbox returns the records
        as array elements. Before the fix, the wrapper form parsed to a
        single EMPTY item and every real preference was dropped —
        `_data_list` normalizes a lone data object into a one-element
        list, which made the nested branch unreachable."""
        resp = PreferencesAndAuthorizationsResponse.from_dict({
            "data": {
                "id": "1", "type": "preferences-and-authorizations",
                "attributes": {
                    "preferencesAndAuthorizations": [
                        {"formattedAccount": "10001843",
                         "accountPreferences": {"isMarginEnabled": True}},
                        {"formattedAccount": "10001112",
                         "accountPreferences": {"isMarginEnabled": False}},
                    ],
                    "errors": [{"account": "10009999", "message": "not found"}],
                },
            },
        })
        assert [i.formatted_account for i in resp.items] == [
            "10001843", "10001112",
        ]
        assert resp.items[0].account_preferences is not None
        assert resp.items[0].account_preferences.is_margin_enabled is True
        # Partial failures ride alongside the successes in a 200.
        assert len(resp.errors) == 1

    def test_preferences_response_sandbox_array_shape_still_works(self):
        resp = PreferencesAndAuthorizationsResponse.from_dict({
            "data": [
                {"attributes": {"formattedAccount": "1234",
                                "accountPreferences": {"isMarginEnabled": True}}},
            ],
        })
        assert len(resp.items) == 1
        assert resp.items[0].formatted_account == "1234"
        assert resp.items[0].account_preferences.is_margin_enabled is True

    def test_preferences_carry_undeclared_master_accounts_and_margin_type(self):
        """Both fields were invisible until the wrapper-shape fix let the
        real records through — `masterAccounts` on the record and
        `marginType` alongside isMarginEnabled."""
        resp = PreferencesAndAuthorizationsResponse.from_dict({
            "data": {"attributes": {"preferencesAndAuthorizations": [{
                "formattedAccount": "10001843",
                "masterAccounts": ["8174295"],
                "accountPreferences": {"isMarginEnabled": False,
                                       "marginType": "Cash"},
            }]}},
        })
        item = resp.items[0]
        assert item.master_accounts == ["8174295"]
        assert item.account_preferences.margin_type == "Cash"

    def test_position_carries_undeclared_cusip(self):
        from schwab_advisor.models import ListPosition, Position

        pos = Position.from_dict({"symbol": "AAPL", "cusipNumber": "037833100"})
        lst = ListPosition.from_dict({"symbol": "AAPL", "cusipNumber": "037833100"})
        assert pos.cusip_number == "037833100"
        assert lst.cusip_number == "037833100"

    def test_transaction_carries_undeclared_order_ids(self):
        from schwab_advisor.models import Transaction

        t = Transaction.from_dict({"attributes": {
            "action": "Sell", "symbol": "REGN",
            "orderId": 123456, "schwabOrderId": 987654,
        }})
        assert (t.order_id, t.schwab_order_id) == (123456, 987654)

    def test_cost_basis_lots_carry_undeclared_event_id(self):
        from schwab_advisor.models import RglTransactionLot, UglPositionLot

        ugl = UglPositionLot.from_dict({"lotId": "L1", "eventId": "E1"})
        rgl = RglTransactionLot.from_dict({"lotId": "L2", "eventId": "E2"})
        assert (ugl.event_id, rgl.event_id) == ("E1", "E2")

    def test_document_preference_issuer_disclosure_opt_out(self):
        from schwab_advisor.models import DocumentPreference

        dp = DocumentPreference.from_dict({
            "formattedAccount": "1234", "isIssuerDisclosureOptedOut": True,
        })
        assert dp.is_issuer_disclosure_opted_out is True

    def test_cost_basis_values_stay_formatted_strings(self):
        """Prod returns "$6,436.79" / "1764.42%" / "20.00000" — coercing
        these to float would silently lose the negatives-in-parens and
        "Missing"/"N/A" sentinels."""
        from schwab_advisor.models import UglPosition

        p = UglPosition.from_dict({
            "symbol": "AAPL", "quantity": "20.00000", "costBasis": "$364.81",
            "unrealizedGainLossDollar": "$6,436.79",
            "unrealizedGainLossPercent": "1764.42%",
        })
        assert p.cost_basis == "$364.81"
        assert p.unrealized_gain_loss_percent == "1764.42%"

    def test_transactions_response_has_no_total_count(self):
        """The prod /transactions payload carries no count block — total
        stays None rather than being invented as 0."""
        resp = TransactionsResponse.from_dict({
            "data": [{"id": "1", "attributes": {"action": "Sell"}}],
            "meta": {"paging": {"nextCursor": "c1"}},
        })
        assert resp.total_count is None
        assert resp.next_cursor == "c1"
