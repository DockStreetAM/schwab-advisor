"""Schwab Advisor API client."""

import threading
import uuid
from typing import Callable, Literal

import httpx

# Most Schwab AS endpoints accept a "Mask" / "Show" toggle for PII fields
# (account number, DOB, taxpayer ID, etc.). Defined once here so signatures
# don't repeat the literal at every call site.
MaskMode = Literal["Mask", "Show"]

from .auth import SchwabAuth
from .models import (
    AccountDetail,
    AccountInfo,
    AccountOwnerListResponse,
    AccountProfile,
    AccountProfilesResponse,
    AccountRmd,
    AccountRmdResponse,
    AccountRolesResponse,
    AccountsResponse,
    AccountSummary,
    AccountSyncResponse,
    AddressChangeCreateResponse,
    AddressChangesResponse,
    AlertArchiveResponse,
    AlertDetailResponse,
    AlertsResponse,
    AlertUpdateResponse,
    BalanceDetailResponse,
    BalanceListResponse,
    ClientInquiryResponse,
    CostBasisPreferencesResponse,
    CostBasisRglResponse,
    CostBasisUglResponse,
    DataDeliveryEnrollmentResponse,
    AchTransferResponse,
    MoveMoneyActivitiesResponse,
    TaxWithholdingElectionsResponse,
    WireTransferResponse,
    MoveMoneyActivity,
    DocumentPreferencesResponse,
    MasterAccountsResponse,
    OrdersResponse,
    OrdersStatusResponse,
    PositionDetailResponse,
    PositionListResponse,
    AccountHoldersResponse,
    PreferencesAndAuthorizations,
    PreferencesAndAuthorizationsResponse,
    ProfilesListResponse,
    Role,
    ReportsResponse,
    ServiceRequestCreateResponse,
    StandingInstruction,
    StandingInstructionDetail,
    StandingInstructionsResponse,
    ServiceRequestTopicsResponse,
    StatusEventsPostResponse,
    StatusEventsResponse,
    StatusFeedCreateResponse,
    StatusFeedResponse,
    TransactionDetail,
    TransactionsResponse,
    UglPositionLotsResponse,
    UserAuthorizationsResponse,
)

_DEFAULT_TIMEOUT = httpx.Timeout(10.0, read=30.0)

# AS Account endpoints live under "bulk"; AS Alerts/Service-Request/Status
# under "accounts". Each public method on the client picks a segment.
_API_SEGMENTS = {
    "sandbox": "https://sandbox.schwabapi.com/as-integration/{segment}",
    "production": "https://api.schwabapi.com/as-integration/{segment}",
}

# Segment paths per API product (discovered from OpenAPI specs + sandbox testing)
SEGMENTS = {
    "bulk": "bulk/v2",
    "accounts": "accounts/v2",
    "transfers": "transfers/v1",
    "trading": "trading/v1",
    "trading_upload": "trading/v2",
    "users": "users/v2",
    "irebal": "irebal/v1",
}


def schwab_error_code(exc: httpx.HTTPStatusError) -> str | None:
    """Extract the Schwab error code (e.g. SEC-0001) from a failed response."""
    try:
        errors = exc.response.json().get("errors") or []
        if errors:
            return errors[0].get("code")
    except Exception:
        pass
    return None


def product_not_attached(exc: httpx.HTTPStatusError) -> bool:
    """True when Apigee rejected the ROUTE because it isn't in any API
    product attached to this app — the signature of a product-attachment
    gap or swap, not a token problem.

    The "InvalidAPICallAsNoApiProductMatchFound" marker lives ONLY in the
    401's www-authenticate header; the body is a generic SEC-0001
    envelope, so body-based checks misdiagnose this as an auth failure.
    Schwab has swapped which account product is attached before
    (2026-07-10: AS Account in, Account Inquiry out), so facade methods
    use this to fall back between equivalent routes.
    """
    return exc.response.status_code == 401 and "NoApiProductMatchFound" in (
        exc.response.headers.get("www-authenticate", "")
    )


class SchwabAdvisorClient:
    """Client for interacting with Schwab Advisor Services API."""

    def __init__(
        self,
        auth: SchwabAuth | None = None,
        access_token: str | None = None,
        environment: Literal["sandbox", "production"] | None = None,
        base_url: str | None = None,
        resource_version: int = 1,
    ):
        if auth is None and access_token is None:
            auth = SchwabAuth.from_env()

        if environment is None:
            environment = getattr(auth, "environment", "sandbox") if auth else "sandbox"

        self.auth = auth
        self._access_token = access_token
        self.environment = environment
        self.base_url = base_url
        self.resource_version = resource_version
        self._client: httpx.Client | None = None
        self._client_lock = threading.Lock()

    def _base_url(self, segment: str = "bulk") -> str:
        """Get the base URL for a given API segment."""
        if self.base_url:
            return self.base_url
        seg_path = SEGMENTS.get(segment, segment)
        return _API_SEGMENTS[self.environment].format(segment=seg_path)

    def _get_access_token(self) -> str:
        if self.auth:
            return self.auth.get_access_token()
        return self._access_token

    def _get_headers(
        self,
        has_body: bool = False,
        extra_headers: dict[str, str] | None = None,
        correl_id: str | None = None,
    ) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._get_access_token()}",
            "Schwab-Client-CorrelId": (
                correl_id if correl_id is not None else str(uuid.uuid4())
            ),
            "Schwab-Resource-Version": str(self.resource_version),
            "Accept": "application/vnd.api+json",
        }
        if has_body:
            headers["Content-Type"] = "application/json"
        if extra_headers:
            headers.update(extra_headers)
        return headers

    @staticmethod
    def _format_client_ids(client_ids: dict[str, object]) -> str:
        """Format Schwab-Client-Ids header value from a dict.

        Example: {"masterAccount": "8174295"} -> "masterAccount=8174295"
        {"masterAccount": "X", "account": "Y"} -> "masterAccount=X,account=Y"

        Multiple keys joined with "," (no space) — Schwab rejects whitespace
        between pairs with a 400 Bad Request.

        Values are validated: "," or "=" inside a value would corrupt the
        pair structure (and Schwab 400s on the resulting whitespace-after-
        comma), control characters are header injection, and non-latin-1
        characters make httpx raise UnicodeEncodeError deep in header
        encoding. All three fail here with a clear ValueError instead.
        TODO: unknown whether Schwab supports ANY escaping for legitimate
        comma-containing values (e.g. lastName "Smith, Jr") — the endpoint
        where it matters (/client-inquiries) isn't entitled in sandbox, so
        this can't be probed until Client Inquiry lands (Bundle 2).
        """
        parts = []
        for k, v in client_ids.items():
            if not v:
                continue
            s = str(v)
            if "," in s or "=" in s:
                raise ValueError(
                    f"Schwab-Client-Ids value {s!r} for {k!r} contains "
                    "',' or '=' — Schwab's header format cannot carry "
                    "these characters"
                )
            if any(ord(c) < 32 or ord(c) > 255 for c in s):
                raise ValueError(
                    f"Schwab-Client-Ids value {s!r} for {k!r} contains "
                    "control or non-latin-1 characters, which cannot be "
                    "sent in an HTTP header"
                )
            parts.append(f"{k}={s}")
        return ",".join(parts)

    def __enter__(self):
        self._ensure_client()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _ensure_client(self) -> httpx.Client:
        with self._client_lock:
            if self._client is None:
                self._client = httpx.Client()
            return self._client

    def close(self) -> None:
        """Close the HTTP client and release connections."""
        # getattr: __del__ may run after a failed __init__ (e.g. bad
        # SCHWAB_ENVIRONMENT) before these attributes were assigned.
        lock = getattr(self, "_client_lock", None)
        if lock is None:
            return
        with lock:
            if self._client:
                self._client.close()
                self._client = None

    def __del__(self):
        self.close()

    def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json_data: dict | list | None = None,
        segment: str = "bulk",
        extra_headers: dict[str, str] | None = None,
        correl_id: str | None = None,
    ) -> httpx.Response:
        headers = self._get_headers(
            has_body=json_data is not None,
            extra_headers=extra_headers,
            correl_id=correl_id,
        )
        url = f"{self._base_url(segment)}{path}"

        client = self._ensure_client()
        response = client.request(
            method, url, params=params, json=json_data,
            headers=headers, timeout=_DEFAULT_TIMEOUT,
        )

        response.raise_for_status()
        return response

    def _paginated_params(
        self,
        page_cursor: str | None = None,
        page_limit: int = 500,  # max supported by Schwab API
        include_total_count: bool = False,
        show_account: str | None = None,
    ) -> dict:
        params: dict = {"page[limit]": page_limit}
        if page_cursor:
            params["page[cursor]"] = page_cursor
        if include_total_count:
            params["includeTotalCount"] = "true"
        if show_account is not None:
            params["showAccount"] = show_account
        return params

    # --- cursor-pagination walkers -------------------------------------
    #
    # Both guard against a server bug (or replaying proxy) that returns
    # the same non-empty nextCursor forever, which would otherwise loop
    # unbounded.

    @staticmethod
    def _all_pages(fetch: Callable, get_items: Callable) -> list:
        """Collect items from every page of a cursor-paginated endpoint."""
        out: list = []
        cursor = None
        while True:
            page = fetch(cursor)
            out.extend(get_items(page))
            nxt = page.next_cursor
            if not nxt or nxt == cursor:
                return out
            cursor = nxt

    @staticmethod
    def _find_paged(fetch: Callable, get_items: Callable, pred: Callable):
        """Walk pages until pred matches an item; None when exhausted."""
        cursor = None
        while True:
            page = fetch(cursor)
            for item in get_items(page):
                if pred(item):
                    return item
            nxt = page.next_cursor
            if not nxt or nxt == cursor:
                return None
            cursor = nxt

    # =====================================================================
    # AS Account (segment: bulk)
    # =====================================================================

    def get_account_profiles(
        self,
        page_cursor: str | None = None,
        page_limit: int = 500,
        include_total_count: bool = False,
        show_account: MaskMode = "Mask",
    ) -> AccountProfilesResponse:
        """Retrieve account profiles for all authorized accounts.

        Sandbox + Production: VERIFIED (prod 2026-07-10, when AS Account
        was attached to the prod app — it 401'd before that).
        """
        params = self._paginated_params(
            page_cursor,
            page_limit,
            include_total_count,
            show_account=show_account,
        )
        response = self._request("GET", "/account-profiles", params=params)
        return AccountProfilesResponse.from_dict(response.json())

    def get_all_account_profiles(
        self,
        show_account: MaskMode = "Show",
    ) -> list[AccountProfile]:
        """Fetch all account profiles across all pages.

        Sandbox: VERIFIED - pagination loop tested.
        """
        return self._all_pages(
            lambda c: self.get_account_profiles(
                page_cursor=c, show_account=show_account
            ),
            lambda page: page.profiles,
        )

    def get_account_roles(
        self,
        page_cursor: str | None = None,
        page_limit: int = 500,
        include_total_count: bool = False,
        show_account: MaskMode = "Mask",
        show_dob: MaskMode = "Mask",
        show_tax_id: MaskMode = "Mask",
    ) -> AccountRolesResponse:
        """Retrieve account roles for all authorized accounts.

        Sandbox + Production: VERIFIED (prod 2026-07-10 — returns real
        roles with holder details).

        Note: showDOB / showTaxID are accepted by the endpoint but the
        sandbox role records don't carry dateOfBirth / taxId fields, so
        visual proof of unmasking requires production data.
        """
        params = self._paginated_params(
            page_cursor,
            page_limit,
            include_total_count,
            show_account=show_account,
        )
        params["showDOB"] = show_dob
        params["showTaxID"] = show_tax_id
        response = self._request("GET", "/account-roles", params=params)
        return AccountRolesResponse.from_dict(response.json())

    def get_account_rmd(
        self,
        filter_age: str | None = None,
        filter_rmd_remaining: bool | None = None,
        filter_account_type: str | None = None,
        include_total_count: bool = False,
        page_cursor: str | None = None,
        page_limit: int = 500,
        show_account: MaskMode = "Mask",
    ) -> AccountRmdResponse:
        """Retrieve RMD (Required Minimum Distribution) data for retirement accounts.

        Sandbox: PARTIALLY VERIFIED - returns data but all RMD dollar amounts
        are 0.0 in sandbox.
        Production: VERIFIED (2026-07-10 — route attached and parsing).

        Args:
            filter_age: One of RMDAge, NotRMDAge, FirstRMDDueThisYear.
            filter_rmd_remaining: Filter by accounts with remaining RMD.
            filter_account_type: One of RothIRA, InheritedIRA, OtherIRA.
        """
        params = self._paginated_params(
            page_cursor,
            page_limit,
            include_total_count,
            show_account=show_account,
        )
        if filter_age:
            params["filter[age]"] = filter_age
        if filter_rmd_remaining is not None:
            params["filter[rmdRemaining]"] = str(filter_rmd_remaining).lower()
        if filter_account_type:
            params["filter[accountType]"] = filter_account_type
        response = self._request("GET", "/account-rmd", params=params)
        return AccountRmdResponse.from_dict(response.json())

    # =====================================================================
    # AS Account Inquiry (segment: accounts)
    # =====================================================================

    def get_master_accounts(
        self,
        filter_master_account_type: str | None = None,
        filter_authority: str | None = None,
        filter_is_iip: str | None = None,
        sort_by: str | None = None,
        sort_direction: Literal["Asc", "Desc"] | None = None,
        page_cursor: str | None = None,
        page_limit: int = 500,
        show_account: MaskMode = "Mask",
    ) -> MasterAccountsResponse:
        """Retrieve master accounts.

        Sandbox + Production: VERIFIED 2026-07-09, but removed from the
        prod app 2026-07-10 (mistaken inclusion, corrected by Schwab;
        Account Inquiry is planned for a future bundle) — 401s
        InvalidAPICallAsNoApiProductMatchFound until then. Broker's
        sandbox tenant app also lacks Account Inquiry; sandbox
        verification used the all-APIs app.

        Args:
            filter_master_account_type: One of FA, BT, SL.
            filter_authority: One of Read, Upload, Download, Trade, MoveMoney.
            filter_is_iip: One of IIPOnly, NonIIP.
            sort_by: One of MasterAccount, MasterAccountType.
        """
        params = self._paginated_params(
            page_cursor,
            page_limit,
            show_account=show_account,
        )
        if filter_master_account_type:
            params["filter[masterAccountType]"] = filter_master_account_type
        if filter_authority:
            params["filter[authority]"] = filter_authority
        if filter_is_iip:
            params["filter[isIip]"] = filter_is_iip
        if sort_by:
            params["sortBy"] = sort_by
        if sort_direction:
            params["sortDirection"] = sort_direction
        response = self._request(
            "GET", "/master-accounts", params=params, segment="accounts"
        )
        return MasterAccountsResponse.from_dict(response.json())

    def get_accounts(
        self,
        page_cursor: str | None = None,
        page_limit: int = 500,
        show_account: MaskMode = "Mask",
        filter_is_iip: Literal["IIPOnly", "NonIIP"] | None = None,
        sort_by: Literal[
            "Account", "AccountTitle1", "LinkedToMasterDate",
            "FormattedTaxpayerId",
        ] | None = None,
        sort_direction: Literal["Asc", "Desc"] | None = None,
        show_tax_id: MaskMode | None = None,
    ) -> AccountsResponse:
        """Retrieve all accounts under authorized master accounts.

        Sandbox + Production: VERIFIED 2026-07-09 (real accounts with
        pagination; prod responses include a `clientIds` field the
        OpenAPI spec doesn't declare, parsed as client_ids), but removed
        from the prod app 2026-07-10 (mistaken inclusion; returns in a
        future bundle). Use get_account_profiles for prod account
        discovery until then.

        Args:
            filter_is_iip: Restrict to IIP or non-IIP accounts.
            sort_by: Field to sort by (default Account).
            sort_direction: Asc or Desc (default Asc).
            show_tax_id: Mask or show ``formattedTaxpayerId``. Independent
                of ``show_account``, which governs the account number.
        """
        params = self._paginated_params(
            page_cursor,
            page_limit,
            show_account=show_account,
        )
        if filter_is_iip:
            params["filter[isIip]"] = filter_is_iip
        if sort_by:
            params["sortBy"] = sort_by
        if sort_direction:
            params["sortDirection"] = sort_direction
        if show_tax_id is not None:
            params["showTaxID"] = show_tax_id
        response = self._request(
            "GET", "/accounts", params=params, segment="accounts"
        )
        return AccountsResponse.from_dict(response.json())

    def get_all_accounts(
        self,
        show_account: MaskMode = "Show",
    ) -> list[AccountInfo]:
        """Fetch all Account Inquiry accounts across all pages.

        Mirror of get_all_account_profiles for the accounts/v2 product;
        the facade methods use whichever of the two is attached.
        """
        return self._all_pages(
            lambda c: self.get_accounts(page_cursor=c, show_account=show_account),
            lambda page: page.accounts,
        )

    def search_account_owners(
        self,
        first_name: str | None = None,
        last_name: str | None = None,
        organization_name: str | None = None,
        client_id: int | None = None,
    ) -> AccountOwnerListResponse:
        """Search for account owners by name or client ID.

        Sandbox + Production: VERIFIED 2026-07-09 (last-name search
        returns real owners with account links), but removed from the
        prod app 2026-07-10 with the rest of Account Inquiry (mistaken
        inclusion; returns in a future bundle).
        """
        body: dict = {}
        if first_name:
            body["firstName"] = first_name
        if last_name:
            body["lastName"] = last_name
        if organization_name:
            body["organizationName"] = organization_name
        if client_id:
            body["clientId"] = client_id
        response = self._request(
            "POST", "/account-owners/list", json_data=body, segment="accounts"
        )
        return AccountOwnerListResponse.from_dict(response.json())

    # =====================================================================
    # AS Account Synchronization (segment: bulk)
    # =====================================================================

    def get_account_sync(
        self,
        filter_last_updated_date: str | None = None,
        page_cursor: str | None = None,
        page_limit: int = 500,
        show_account: MaskMode = "Mask",
        show_dob: MaskMode = "Mask",
        show_tax_id: MaskMode = "Mask",
    ) -> AccountSyncResponse:
        """Retrieve account synchronization data.

        Sandbox: VERIFIED - returns sync records with client IDs.

        Args:
            filter_last_updated_date: ISO datetime for delta sync. Returns
                only accounts updated after this date/time. This is the
                primary use case for this endpoint.
        """
        params = self._paginated_params(
            page_cursor,
            page_limit,
            show_account=show_account,
        )
        params["showDOB"] = show_dob
        params["showTaxID"] = show_tax_id
        if filter_last_updated_date:
            params["filter[lastUpdatedDate]"] = filter_last_updated_date
        response = self._request("GET", "/account-sync", params=params)
        return AccountSyncResponse.from_dict(response.json())

    # =====================================================================
    # AS Accounts Preferences and Authorizations (segment: accounts)
    # =====================================================================

    def get_preferences_and_authorizations(
        self,
        formatted_accounts: list[str],
        show_account: MaskMode = "Mask",
    ) -> PreferencesAndAuthorizationsResponse:
        """Retrieve preferences and authorizations (MoneyLink, IA authority, etc.).

        Sandbox + Production: VERIFIED (prod 2026-07-09). Nested objects
        can come back EMPTY ({}) — the model maps those to None; sandbox
        has also returned an undocumented `masterAccounts` key (preserved
        in raw_data).
        Body shape is flat ({"Accounts": [...], "showAccount": "..."}), not
        JSON:API. showAccount must be sent in the body — query-string form
        is silently ignored by the endpoint.
        """
        body = {"Accounts": formatted_accounts, "showAccount": show_account}
        response = self._request(
            "POST", "/preferences-and-authorizations/list",
            json_data=body, segment="accounts",
        )
        return PreferencesAndAuthorizationsResponse.from_dict(response.json())

    # =====================================================================
    # AS Address Change (segment: accounts)
    # =====================================================================

    def get_address_changes(
        self,
        filter_status: str | None = None,
        filter_last_updated_date: str | None = None,
        include_customer: bool = False,
        show_account: MaskMode = "Mask",
    ) -> AddressChangesResponse:
        """Retrieve address changes across all authorized accounts.

        Sandbox: VERIFIED for the contract (200, all filters and
        include=customer accepted) but data is always EMPTY: an address
        change requires client confirmation before it enters the readable
        pipeline, and no sandbox client ever confirms — so even changes
        created via create_address_change never appear here. Field names
        are from Schwab's documented example response but have not been
        seen in a live API response. The service also has transient
        multi-minute windows where reads time out (observed 2026-08-06
        and 2026-08-07); retry on timeout.
        No Schwab-Client-Ids header needed (firm-level endpoint).
        Supports JSON:API relationships and include=customer sideloading.

        Args:
            filter_status: One of Completed, Draft, PendingClientApproval,
                SubmittedToSchwab, SubmittedToSchwabException, Voided.
            filter_last_updated_date: ISO date string. Must be within last
                6 days (Schwab enforced). Default is 6 days prior.
            include_customer: If True, includes related customer data via
                JSON:API sideloading in response.included.
        """
        params: dict = {"showAccount": show_account}
        if filter_status:
            params["filter[status]"] = filter_status
        if filter_last_updated_date:
            params["filter[lastUpdatedDate]"] = filter_last_updated_date
        if include_customer:
            params["include"] = "customer"
        response = self._request(
            "GET", "/address-changes", params=params, segment="accounts",
        )
        return AddressChangesResponse.from_dict(response.json())

    def get_address_change(
        self,
        action_id: str,
        show_account: MaskMode = "Mask",
    ) -> AddressChangesResponse:
        """Retrieve a specific address change by action ID.

        Sandbox: route VERIFIED live (2026-08-07) but no action is ever
        retrievable: ids returned by create_address_change answer 404
        because the created change waits on client confirmation, which no
        sandbox client ever gives. Expect 404 in sandbox; retry on the
        service's transient read-timeout windows. AddressChangesResponse
        already normalizes single-object `data` to a one-item `.changes`
        list, so callers can access `.changes[0]`.
        """
        params = {"showAccount": show_account}
        response = self._request(
            "GET", f"/address-changes/{action_id}", params=params,
            segment="accounts",
        )
        return AddressChangesResponse.from_dict(response.json())

    def create_address_change(
        self,
        master_account: int,
        user_entered_addresses: list[dict],
        customer_search_criteria: dict | None = None,
        envelope_id: str | None = None,
    ) -> AddressChangeCreateResponse:
        """Submit an address change request.

        Sandbox: VERIFIED (2026-08-06/07) - returns 201 in ~1.5s with the
        new action id and a COA-prefixed envelopeId when the search
        criteria match exactly one customer. Gotchas: an EMPTY
        user_entered_addresses list crashes the service (empty-body 500);
        overly generic names match many fixture customers and have
        preceded service hang windows — use distinctive names. The created
        change is NOT retrievable afterwards (client-confirmation gate,
        see get_address_change).

        Args:
            master_account: Master account number (integer).
            user_entered_addresses: List of new address dicts with keys:
                addressLine1, city, state, zipCode, country, and optionally
                addressLine2-4, zipSuffix.
            customer_search_criteria: Dict with firstName, lastName, and
                optionally taxpayerId, dateOfBirth to identify the customer.
            envelope_id: Optional Action Center envelope ID.
        """
        body: dict = {
            "masterAccount": master_account,
            "userEnteredAddresses": user_entered_addresses,
        }
        if customer_search_criteria:
            body["customerSearchCriteria"] = customer_search_criteria
        if envelope_id:
            body["envelopeId"] = envelope_id
        response = self._request(
            "POST", "/address-changes", json_data=body, segment="accounts"
        )
        return AddressChangeCreateResponse.from_dict(response.json())

    # =====================================================================
    # AS Alerts (segment: accounts)
    # =====================================================================

    def get_alerts(
        self,
        page_cursor: str | None = None,
        page_limit: int = 500,
        filter_types: list[str] | None = None,
        filter_subjects: list[str] | None = None,
        filter_start_date: str | None = None,
        filter_end_date: str | None = None,
        sort_by: Literal[
            "AccountName", "CreatedDate", "FormattedAccount",
            "FormattedMasterAccount", "Priority", "ReplyType",
            "Status", "Subject", "Type",
        ] | None = None,
        sort_direction: Literal["Asc", "Desc"] | None = None,
        show_account: MaskMode = "Mask",
        filter_status: str | None = None,
        filter_is_archived: bool | None = None,
        filter_origin_type: Literal["Original", "Copied"] | None = None,
        schwab_client_ids: dict[str, str] | None = None,
        correl_id: str | None = None,
    ) -> AlertsResponse:
        """Retrieve alerts for all authorized master accounts.

        Sandbox + Production: VERIFIED — returns alerts with full data.

        Args:
            filter_status: One of "New", "Viewed", "ResponseSent".
            filter_is_archived: Filter by archived status.
            filter_origin_type: "Original" or "Copied".
            schwab_client_ids: Optional dict like {"account": "..."} or
                {"masterAccount": "..."} — sent as Schwab-Client-Ids header
                to scope alerts to specific accounts.
            correl_id: Optional override for Schwab-Client-CorrelId (empty
                string reproduces the 400 error).
        """
        params = self._paginated_params(
            page_cursor,
            page_limit,
            show_account=show_account,
        )
        if filter_types:
            params["filter[types]"] = ", ".join(filter_types)
        if filter_subjects:
            params["filter[subjects]"] = ", ".join(filter_subjects)
        if filter_start_date:
            params["filter[startDate]"] = filter_start_date
        if filter_end_date:
            params["filter[endDate]"] = filter_end_date
        if filter_status:
            params["filter[status]"] = filter_status
        if filter_is_archived is not None:
            params["filter[isArchived]"] = str(filter_is_archived).lower()
        if filter_origin_type:
            params["filter[originType]"] = filter_origin_type
        if sort_by:
            params["sortBy"] = sort_by
        if sort_direction:
            params["sortDirection"] = sort_direction
        extra = None
        if schwab_client_ids:
            extra = {"Schwab-Client-Ids": self._format_client_ids(schwab_client_ids)}
        response = self._request(
            "GET", "/alerts", params=params, segment="accounts",
            extra_headers=extra, correl_id=correl_id,
        )
        return AlertsResponse.from_dict(response.json())

    def get_alert_detail(
        self,
        alert_id: int | str,
        master_account: str | None = None,
        account: str | None = None,
        show_account: MaskMode = "Mask",
        correl_id: str | None = None,
    ) -> AlertDetailResponse:
        """Get full detail for a single alert.

        Sandbox + Production: VERIFIED — returns detailed alert with HTML
        detailText, statusHistory, and audit fields. Schwab requires the
        Schwab-Client-Ids header; callers should always pass at least
        ``master_account``. Omitting it returns 400.

        Args:
            alert_id: The alert id.
            master_account: Master account scope for Schwab-Client-Ids header.
            account: Sub-account scope — combined with master_account the header
                becomes ``masterAccount=X,account=Y``.
            show_account: Mask (default) or Show.
        """
        extra = None
        ids: dict[str, str] = {}
        if master_account:
            ids["masterAccount"] = master_account
        if account:
            ids["account"] = account
        if ids:
            extra = {"Schwab-Client-Ids": self._format_client_ids(ids)}
        response = self._request(
            "GET",
            f"/alerts/detail/{alert_id}",
            params={"showAccount": show_account},
            segment="accounts",
            extra_headers=extra,
            correl_id=correl_id,
        )
        return AlertDetailResponse.from_dict(response.json())

    def archive_alerts(self, alert_ids: list[int]) -> AlertArchiveResponse:
        """Archive one or more alerts.

        Sandbox: VERIFIED - archives alerts and returns per-alert status.
        Uses flat body {"alertIds": [int]} (not JSON:API). IDs are integers.
        """
        body = {"alertIds": alert_ids}
        response = self._request(
            "POST", "/alerts/archive", json_data=body, segment="accounts"
        )
        return AlertArchiveResponse.from_dict(response.json())

    def update_alert(
        self,
        alert_id: int | str,
        action: Literal["Unarchive", "Unread"],
        correl_id: str | None = None,
    ) -> AlertUpdateResponse:
        """Unarchive an alert or mark it as unread.

        Sandbox + Production: VERIFIED — returns 204 No Content on success.
        Per OpenAPI spec, body is flat {"action": value}.

        Args:
            alert_id: The alert id.
            action: "Unarchive" to unarchive, "Unread" to mark as unread.
        """
        body = {"action": action}
        response = self._request(
            "PATCH", f"/alerts/{alert_id}", json_data=body, segment="accounts",
            correl_id=correl_id,
        )
        if response.status_code == 204:
            return AlertUpdateResponse(id=str(alert_id), raw_data=None)
        return AlertUpdateResponse.from_dict(response.json())

    # =====================================================================
    # AS Balances (segment: accounts)
    # =====================================================================

    def get_balance_detail(
        self,
        account: str,
        include_open_orders: bool = False,
        page_cursor: str | None = None,
        page_limit: int = 500,
        show_account: MaskMode = "Mask",
    ) -> BalanceDetailResponse:
        """Retrieve detailed balance info for a specific account.

        Sandbox: VERIFIED - returns full balance breakdown (50+ fields).
        Production: VERIFIED 2026-07-28. Real accounts populate only the
        fields that apply to them (a cash account returned 13 of the
        spec's 52 — margin/PAA blocks stay zero), so never read a zero
        here as "missing data".

        Args:
            include_open_orders: Include open order amounts in balances.
        """
        params = self._paginated_params(
            page_cursor,
            page_limit,
            show_account=show_account,
        )
        if include_open_orders:
            params["includeOpenOrders"] = "true"
        response = self._request(
            "GET", "/balances/detail", params=params, segment="accounts",
            extra_headers={"Schwab-Client-Ids": self._format_client_ids({"account": account})},
        )
        return BalanceDetailResponse.from_dict(response.json())

    def get_balances_list(
        self,
        accounts: list[str],
        include_open_orders: bool = False,
        sort_direction: Literal["Asc", "Desc"] | None = None,
        show_account: MaskMode = "Mask",
    ) -> BalanceListResponse:
        """Retrieve balances for multiple accounts (max 200 per call).

        Sandbox: VERIFIED - returns nested balances array.
        Production: VERIFIED 2026-07-28 (3 accounts; cross-account
        totals populated). Partial failures come back as a 200 with
        entries in `errors` — check it.
        Uses flat body {"Accounts": [...]}; the optional fields ride in
        the same body per the Balances spec's BalancesListPostRequest.

        Args:
            include_open_orders: Include open order amounts in balances.
            sort_direction: "Asc" or "Desc" (service default: Asc).
        """
        body: dict = {"Accounts": accounts, "showAccount": show_account}
        if include_open_orders:
            body["includeOpenOrders"] = True
        if sort_direction:
            body["sortDirection"] = sort_direction
        response = self._request(
            "POST", "/balances/list", json_data=body, segment="accounts"
        )
        return BalanceListResponse.from_dict(response.json())

    # =====================================================================
    def get_cost_basis_ugl_position_lots(
        self,
        account: int | str,
        position_ids: list[str],
        show_account: MaskMode = "Mask",
    ) -> UglPositionLotsResponse:
        """Retrieve unrealized gain/loss lot-level detail for specific positions.

        Production: VERIFIED 2026-07-28 (3 positions -> 5 lots; every
        position ID from get_cost_basis_ugl_positions was accepted).
        Lots carry an undeclared `eventId`.
        Sandbox: VERIFIED - returns lot-level data with holdingPeriod,
        costPerShare, acquiredDate. Values are formatted strings ("N/A" for
        unavailable). Response includes invalidPositions for unknown IDs.

        Args:
            account: Account number as integer.
            position_ids: List of positionId strings from get_cost_basis_ugl_positions().
        """
        body = {
            "account": account,
            "positionIds": position_ids,
            "showAccount": show_account,
        }
        response = self._request(
            "POST", "/cost-basis/ugl-position-lots/list",
            json_data=body, segment="accounts",
        )
        return UglPositionLotsResponse.from_dict(response.json())

    # AS Client Inquiry (segment: accounts)
    # =====================================================================

    def search_clients(
        self,
        first_name: str | None = None,
        last_name: str | None = None,
        organization_name: str | None = None,
        page_cursor: str | None = None,
        page_limit: int = 500,
        sort_by: Literal["AccountName", "ClientID"] | None = None,
        sort_direction: Literal["Asc", "Desc"] | None = None,
    ) -> ClientInquiryResponse:
        """Search for clients by name.

        Sandbox: VERIFIED - returns client info with IDs. Search criteria goes
        in the Schwab-Client-Ids header (e.g. "firstName=TEST,lastName=DOE"),
        not in query params. This is unique to this endpoint.

        At least one of first_name, last_name, or organization_name is required.

        Args:
            sort_by: AccountName or ClientID (default ClientID).
            sort_direction: Asc or Desc (default Asc).
        """
        header = self._format_client_ids({
            "firstName": first_name,
            "lastName": last_name,
            "organizationName": organization_name,
        })
        if not header:
            raise ValueError("At least one of first_name, last_name, or organization_name is required")
        params = self._paginated_params(page_cursor, page_limit)
        if sort_by:
            params["sortBy"] = sort_by
        if sort_direction:
            params["sortDirection"] = sort_direction
        response = self._request(
            "GET", "/client-inquiries", params=params, segment="accounts",
            extra_headers={"Schwab-Client-Ids": header},
        )
        return ClientInquiryResponse.from_dict(response.json())

    # =====================================================================
    # AS Cost Basis (segment: accounts)
    # =====================================================================

    def get_cost_basis_account_preferences(
        self,
        account: str | None = None,
        master_account: str | None = None,
        page_cursor: str | None = None,
        page_limit: int = 500,
        show_account: MaskMode = "Mask",
    ) -> CostBasisPreferencesResponse:
        """Retrieve cost basis account preferences.

        Sandbox: VERIFIED - masterAccount= returns 25 accounts with full
        preference data (accountingMethod, initialCostBasisSource, etc.).
        Production: VERIFIED 2026-07-28 (566 accounts under one master;
        both the account= and masterAccount= forms).
        Supports both account= (single) and masterAccount= (all under master).

        Args:
            account: Single account number (Schwab-Client-Ids: account=X).
            master_account: Master account (Schwab-Client-Ids: masterAccount=X).
                Returns preferences for all accounts under the master.
                One of account or master_account is required.
        """
        if master_account:
            client_ids = f"masterAccount={master_account}"
        elif account:
            client_ids = f"account={account}"
        else:
            raise ValueError("Either account or master_account is required")
        params = self._paginated_params(
            page_cursor,
            page_limit,
            show_account=show_account,
        )
        response = self._request(
            "GET", "/cost-basis/account-preferences", params=params,
            segment="accounts",
            extra_headers={"Schwab-Client-Ids": client_ids},
        )
        return CostBasisPreferencesResponse.from_dict(response.json())

    def get_cost_basis_rgl_transactions(
        self,
        account: str,
        filter_start_date: str | None = None,
        filter_end_date: str | None = None,
        sort_by: str | None = None,
        sort_direction: Literal["Asc", "Desc"] | None = None,
        page_cursor: str | None = None,
        page_limit: int = 100,  # RGL max is 100
        show_account: MaskMode = "Mask",
    ) -> CostBasisRglResponse:
        """Retrieve realized gain/loss transactions.

        Production: VERIFIED 2026-07-28 (25 transactions with lots; the
        100 page[limit] cap is a hard 400, unlike UGL's 500). Lots carry
        an undeclared `eventId`.
        Sandbox: VERIFIED - returns 3 RGL transactions for account 93319284
        with AMD, GSAT, PYPL. Values are formatted strings with parentheses
        for negatives (e.g. "($349.02)"). Includes transactionLots.
        Max page[limit] is 100.

        Args:
            filter_start_date: Transactions closed on/after this date.
                Requires filter_end_date. Default is Jan 1 two years back.
            filter_end_date: Transactions closed on/before this date.
                Requires filter_start_date. Default is today.
            sort_by: e.g. "Symbol"
        """
        params = self._paginated_params(
            page_cursor,
            page_limit,
            show_account=show_account,
        )
        if filter_start_date:
            params["filter[startDate]"] = filter_start_date
        if filter_end_date:
            params["filter[endDate]"] = filter_end_date
        if sort_by:
            params["sortBy"] = sort_by
        if sort_direction:
            params["sortDirection"] = sort_direction
        response = self._request(
            "GET", "/cost-basis/rgl-transactions", params=params,
            segment="accounts",
            extra_headers={"Schwab-Client-Ids": self._format_client_ids({"account": account})},
        )
        return CostBasisRglResponse.from_dict(response.json())

    def get_cost_basis_ugl_positions(
        self,
        account: str,
        sort_by: str | None = None,
        sort_direction: Literal["Asc", "Desc"] | None = None,
        page_cursor: str | None = None,
        page_limit: int = 500,  # UGL max is 500 (unlike RGL's 100)
        show_account: MaskMode = "Mask",
    ) -> CostBasisUglResponse:
        """Retrieve unrealized gain/loss positions.

        Production: VERIFIED 2026-07-28 (25 positions + summary).
        Sandbox: VERIFIED - returns 5 UGL positions for account 14217596.
        Values are formatted strings (e.g. "$257,525.32", "Missing").
        Max page[limit] is 500 (higher than RGL's 100).

        Args:
            sort_by: One of CostBasis, MarketValue, Quantity, SecurityName,
                Symbol, UnrealizedGainLossDollar, UnrealizedGainLossPercent.
                Default: Symbol.
        """
        params = self._paginated_params(
            page_cursor,
            page_limit,
            show_account=show_account,
        )
        if sort_by:
            params["sortBy"] = sort_by
        if sort_direction:
            params["sortDirection"] = sort_direction
        response = self._request(
            "GET", "/cost-basis/ugl-positions", params=params,
            segment="accounts",
            extra_headers={"Schwab-Client-Ids": self._format_client_ids({"account": account})},
        )
        return CostBasisUglResponse.from_dict(response.json())

    # =====================================================================
    # AS Document Preferences (segment: accounts)
    # =====================================================================

    def get_document_preferences(
        self,
        accounts: list[str],
        show_account: MaskMode = "Mask",
    ) -> DocumentPreferencesResponse:
        """Retrieve document delivery preferences for accounts.

        Sandbox + Production: VERIFIED (prod 2026-07-09).
        Returns delivery preferences, report preferences,
        and issuer communications settings. showAccount must be sent in the
        body — query-string form is silently ignored.
        """
        body = {"Accounts": accounts, "showAccount": show_account}
        response = self._request(
            "POST", "/document-preferences/list", json_data=body, segment="accounts"
        )
        return DocumentPreferencesResponse.from_dict(response.json())

    # =====================================================================
    # AS Man Fees File Upload (segment: accounts)
    # =====================================================================

    def upload_manfees(
        self,
        base64_file_content: str,
    ) -> None:
        """Upload management fees file (base64-encoded fee file).

        Sandbox: VERIFIED - uploads successfully, returns 204.
        File format is CSV: account_number,fee_amount,name per line.

        Args:
            base64_file_content: Base64-encoded fee file content.
        """
        body = {"Base64EncodedFileContent": base64_file_content}
        self._request(
            "POST", "/upload-manfees", json_data=body, segment="accounts"
        )

    # =====================================================================
    # AS Positions (segment: accounts)
    # =====================================================================

    def get_position_detail(
        self,
        account: str,
        filter_security_type: str | None = None,
        filter_symbol: str | None = None,
        sort_by: str | None = None,
        sort_direction: Literal["Asc", "Desc"] | None = None,
        page_cursor: str | None = None,
        page_limit: int = 500,
        show_account: MaskMode = "Mask",
    ) -> PositionDetailResponse:
        """Retrieve detailed position info for a specific account.

        Sandbox: VERIFIED - returns positions with market values, quantities.
        Production: VERIFIED 2026-07-28 (25 positions; summed market
        value matched the rollup exactly). Prod also returns an
        undeclared `cusipNumber` on every row — parsed onto Position.

        Args:
            filter_security_type: One of Equity, MutualFunds, Options,
                FixedIncome, Other.
            filter_symbol: Filter by ticker/CUSIP.
            sort_by: One of AreCapitalGainsReinvested, AreDividendsReinvested,
                DayChange, MarketValue, Quantity, SecurityName, SecurityType, Symbol.
        """
        params = self._paginated_params(
            page_cursor,
            page_limit,
            show_account=show_account,
        )
        if filter_security_type:
            params["filter[securityType]"] = filter_security_type
        if filter_symbol:
            params["filter[symbol]"] = filter_symbol
        if sort_by:
            params["sortBy"] = sort_by
        if sort_direction:
            params["sortDirection"] = sort_direction
        response = self._request(
            "GET", "/positions/detail", params=params, segment="accounts",
            extra_headers={"Schwab-Client-Ids": self._format_client_ids({"account": account})},
        )
        return PositionDetailResponse.from_dict(response.json())

    def get_positions_list(
        self,
        accounts: list[str],
        security_type: str | None = None,
        symbol: str | None = None,
        page_cursor: str | None = None,
        page_limit: int | None = None,
        sort_by: str | None = None,
        sort_direction: Literal["Asc", "Desc"] | None = None,
        show_account: MaskMode = "Mask",
    ) -> PositionListResponse:
        """Retrieve positions for multiple accounts.

        Sandbox: VERIFIED - returns positions across multiple accounts.
        Production: VERIFIED 2026-07-28 (56 positions across 3 accounts).
        Unlike /positions/detail these rows carry account naming, plus
        the undeclared `cusipNumber`.
        Uses flat body {"Accounts": [...]}; optional fields ride in the
        same body per the Positions spec's PositionsListPostRequest
        (pagination is body-form here, not query-string).

        Args:
            security_type: One of Equity, MutualFunds, Options,
                FixedIncome, Other.
            symbol: Filter by ticker/CUSIP/Schwab security number.
            sort_by: One of AreCapitalGainsReinvested,
                AreDividendsReinvested, FormattedAccount, MarketValue,
                Quantity, SecurityName, SecurityType, Symbol.
            sort_direction: "Asc" or "Desc" (service default: Asc).
        """
        body: dict = {"Accounts": accounts, "showAccount": show_account}
        if security_type:
            body["securityType"] = security_type
        if symbol:
            body["symbol"] = symbol
        if page_cursor:
            body["pageCursor"] = page_cursor
        if page_limit is not None:
            body["pageLimit"] = page_limit
        if sort_by:
            body["sortBy"] = sort_by
        if sort_direction:
            body["sortDirection"] = sort_direction
        response = self._request(
            "POST", "/positions/list", json_data=body, segment="accounts"
        )
        return PositionListResponse.from_dict(response.json())

    # =====================================================================
    # AS Profiles (segment: accounts)
    # =====================================================================

    def get_account_holder(
        self,
        account: str,
        account_holder_id: str,
        show_account: MaskMode = "Mask",
        show_dob: MaskMode = "Mask",
        show_tax_id: MaskMode = "Mask",
    ) -> AccountHoldersResponse:
        """Retrieve detailed profile for a specific account holder.

        Sandbox: VERIFIED - returns full holder profile with employment,
        citizenship, addresses. Requires BOTH account and accountHolderId
        in the Schwab-Client-Ids header (comma-separated).
        Get accountHolderIds from search_account_owners() or get_account_roles().

        Args:
            account: Account number.
            account_holder_id: Holder ID (from account owners/roles).
            show_dob: Mask or show date of birth.
            show_tax_id: Mask or show taxpayer ID.
        """
        params = {
            "showAccount": show_account,
            "showDOB": show_dob,
            "showTaxID": show_tax_id,
        }
        response = self._request(
            "GET", "/profiles/account-holders", params=params, segment="accounts",
            extra_headers={
                "Schwab-Client-Ids": self._format_client_ids({"account": account, "accountHolderId": account_holder_id})
            },
        )
        return AccountHoldersResponse.from_dict(response.json())

    def get_profiles(
        self,
        accounts: list[str],
        include_iip: Literal["IIPOnly", "NonIIP"] | None = None,
        show_account: MaskMode | None = None,
    ) -> ProfilesListResponse:
        """Retrieve detailed profiles for specific accounts.

        Sandbox: VERIFIED - returns full profile with address, registration type,
        email, phone numbers. Uses flat body {"Accounts": [...]}.

        NOTE: the service does NOT always report accounts it could not
        resolve. Some come back in ``invalid_accounts``; others (verified
        2026-07-29 on sandbox account 10708520, which 404s when requested
        alone) are omitted from ``profiles`` with an EMPTY error list.
        Compare ``len(resp.profiles)`` against the accounts you asked for
        rather than trusting the error channel.

        Args:
            include_iip: Restrict to IIP or non-IIP accounts. All accounts
                are returned when omitted.
            show_account: Mask or show the account numbers.
        """
        body: dict = {"Accounts": accounts}
        if include_iip:
            body["includeIip"] = include_iip
        if show_account is not None:
            body["showAccount"] = show_account
        response = self._request(
            "POST", "/profiles/list", json_data=body, segment="accounts"
        )
        return ProfilesListResponse.from_dict(response.json())

    # =====================================================================
    # AS Reports (segment: accounts)
    # =====================================================================

    def get_reports(
        self,
        account: str,
        report_type: Literal["Statements", "Confirmations", "TaxReports"] = "Statements",
        filter_start_date: str | None = None,
        filter_end_date: str | None = None,
        filter_tax_year: int | None = None,
        sort_direction: Literal["Asc", "Desc"] | None = None,
        page_cursor: str | None = None,
        page_limit: int = 500,
        show_account: MaskMode = "Mask",
    ) -> ReportsResponse:
        """Retrieve reports for a specific account.

        Sandbox: VERIFIED - returns report metadata including reportId,
        reportName, reportType, reportSubtype, preparedByDate.

        Args:
            report_type: Statements (default), Confirmations, or TaxReports.
            filter_start_date: Reports from this date (default 3 months back, max 10 years).
            filter_end_date: Reports through this date (default today).
            filter_tax_year: For TaxReports only (default previous year).
        """
        params = self._paginated_params(
            page_cursor,
            page_limit,
            show_account=show_account,
        )
        params["filter[reportType]"] = report_type
        if filter_start_date:
            params["filter[startDate]"] = filter_start_date
        if filter_end_date:
            params["filter[endDate]"] = filter_end_date
        if filter_tax_year:
            params["filter[taxYear]"] = filter_tax_year
        if sort_direction:
            params["sortDirection"] = sort_direction
        response = self._request(
            "GET", "/reports", params=params, segment="accounts",
            extra_headers={"Schwab-Client-Ids": self._format_client_ids({"account": account})},
        )
        return ReportsResponse.from_dict(response.json())

    def get_report_pdf(
        self,
        account: str,
        report_id: str,
        report_type: Literal["Statements", "Confirmations", "TaxReports"] = "Statements",
        show_account: MaskMode = "Mask",
    ) -> dict:
        """Retrieve a report PDF by ID and type.

        Sandbox: VERIFIED - returns base64-encoded PDF content (270KB+).
        Response includes data.attributes.pdfFile (base64 string).

        Args:
            report_id: From get_reports().reports[].reportId.
            report_type: One of Statements, Confirmations, TaxReports.
        """
        params = {"reportId": report_id, "reportType": report_type, "showAccount": show_account}
        response = self._request(
            "GET", "/reports/pdf", params=params, segment="accounts",
            extra_headers={"Schwab-Client-Ids": self._format_client_ids({"account": account})},
        )
        return response.json()

    # =====================================================================
    # AS Service Request (segment: accounts)
    # =====================================================================

    def get_service_request_topics(
        self,
        page_cursor: str | None = None,
        page_limit: int = 500,
    ) -> ServiceRequestTopicsResponse:
        """Retrieve available service request topics and subtopics.

        Sandbox: VERIFIED - returns 15 topics with subtopics, attachment
        requirements, and max file sizes.
        """
        params = self._paginated_params(page_cursor, page_limit)
        response = self._request(
            "GET", "/service-requests", params=params, segment="accounts"
        )
        return ServiceRequestTopicsResponse.from_dict(response.json())

    def create_service_request(
        self,
        topic_name: str,
        sub_topic_name: str,
        description: str,
        master_account: str | None = None,
        account: str | None = None,
        name: str | None = None,
        schwab_case_id: str | None = None,
        cc_email: bool | None = None,
        files: list[dict] | None = None,
        show_account: MaskMode = "Mask",
    ) -> ServiceRequestCreateResponse:
        """Submit a new service request.

        Sandbox: VERIFIED - creates SR and returns confirmation with ID.

        Args:
            name: Title for the SR (max 60 chars). Separate from description.
            schwab_case_id: Merge into existing Schwab case.
            cc_email: Send email copy to registered email.
            files: Attachments as [{"name": "file.pdf",
                "base64EncodedFileContent": "..."}]. Per OpenAPI spec.

        Use get_service_request_topics() to discover valid topic/subtopic names.
        """
        body: dict = {
            "topicName": topic_name,
            "subTopicName": sub_topic_name,
            "description": description,
            "showAccount": show_account,
        }
        if master_account:
            body["masterAccount"] = master_account
        if account:
            body["account"] = account
        if name:
            body["name"] = name
        if schwab_case_id:
            body["schwabCaseId"] = schwab_case_id
        if cc_email is not None:
            body["ccEmail"] = cc_email
        if files:
            body["files"] = files
        response = self._request(
            "POST", "/service-requests", json_data=body, segment="accounts"
        )
        return ServiceRequestCreateResponse.from_dict(response.json())

    # =====================================================================
    # AS Status (segment: accounts)
    # =====================================================================

    def create_status_feed(
        self,
        status: list[str],
        show_account: MaskMode = "Mask",
        master_accounts: list[str] | None = None,
        accounts: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        time_frame: Literal["CreatedDate", "LastUpdatedDate"] | None = None,
        categories: list[str] | None = None,
        myq_case_id: str | None = None,
        service_request_confirmation_id: str | None = None,
        action_center_envelope_id: str | None = None,
        include_all_events: bool | None = None,
        first_page_only: bool | None = None,
        correl_id: str | None = None,
    ) -> StatusFeedCreateResponse:
        """Create a status feed query.

        Sandbox + Production: VERIFIED (prod 2026-07-09 — returns the
        feed with statusObjects inlined; prefer this over the bare GET
        /status-feed/{id}, which is not attached to the prod product).
        Known valid status values: "New", "Resolved". Uses PascalCase flat body.

        Args:
            status: List of status values (e.g. ["New", "Resolved"]).
            show_account: Whether to mask or show account numbers.
            master_accounts: Scope to specific master accounts.
            accounts: Scope to specific sub-accounts.
            start_date: Earliest date (default 90 days prior).
            end_date: Latest date (default current date).
            time_frame: "CreatedDate" (default) or "LastUpdatedDate".
            categories: Filter by category (e.g. "Account Maintenance",
                "Move Money", "Digital Envelope").
            myq_case_id: Filter to a specific MyQ case (e.g. "WI-123456").
            service_request_confirmation_id: Filter to a service request
                (e.g. "SR813637257").
            action_center_envelope_id: Filter to an Action Center envelope
                (e.g. "842993565").
            include_all_events: If True, include all events per object.
            first_page_only: If True, returns 1000 events; else 2000.
        """
        # The AS Status OpenAPI v2.0.0 spec documents camelCase keys, but
        # both sandbox and production accept PascalCase ("Status",
        # "ShowAccount") for the top-level keys, which downstream consumers
        # have been sending in prod since 2026-05. Optional filter keys below
        # follow the spec's camelCase. If Schwab tightens this and rejects
        # PascalCase in the future, switch the two below to "status" /
        # "showAccount".
        body: dict = {
            "Status": status,
            "ShowAccount": show_account,
        }
        if master_accounts:
            body["masterAccounts"] = master_accounts
        if accounts:
            body["accounts"] = accounts
        if start_date:
            body["startDate"] = start_date
        if end_date:
            body["endDate"] = end_date
        if time_frame:
            body["timeFrame"] = time_frame
        if categories:
            body["categories"] = categories
        if myq_case_id:
            body["myqCaseId"] = myq_case_id
        if service_request_confirmation_id:
            body["serviceRequestConfirmationId"] = service_request_confirmation_id
        if action_center_envelope_id:
            body["actionCenterEnvelopeId"] = action_center_envelope_id
        if include_all_events is not None:
            body["includeAllEvents"] = include_all_events
        if first_page_only is not None:
            body["firstPageOnly"] = first_page_only
        response = self._request(
            "POST", "/status-feed", json_data=body, segment="accounts",
            correl_id=correl_id,
        )
        return StatusFeedCreateResponse.from_dict(response.json())

    def get_status_feed(
        self,
        feed_id: str,
        page_limit: int | None = None,
        show_account: MaskMode | None = None,
        correl_id: str | None = None,
    ) -> StatusFeedResponse:
        """Get status objects for a previously created feed.

        Sandbox: returns all status objects as JSON:API array. The AS Status
        OpenAPI spec documents page[limit] (default 1000) and showAccount;
        sandbox testing previously found page[limit] returned empty results,
        but production behavior may differ. Production note (2026-05): this
        route is currently NOT in the AS Status Production "API Product"
        attached to our prod app — Schwab returns 401 SEC-0001 with
        InvalidAPICallAsNoApiProductMatchFound. Use POST /status-feed
        (which inlines status objects) until Schwab adds this route to
        the product.
        """
        params: dict = {}
        if page_limit is not None:
            params["page[limit]"] = page_limit
        if show_account is not None:
            params["showAccount"] = show_account
        response = self._request(
            "GET", f"/status-feed/{feed_id}",
            params=params or None, segment="accounts",
            correl_id=correl_id,
        )
        return StatusFeedResponse.from_dict(response.json())

    def get_status_events(
        self,
        feed_id: str,
        object_id: str,
        correl_id: str | None = None,
    ) -> StatusEventsResponse:
        """Get status events for a specific object in a feed.

        Sandbox + Production: VERIFIED (prod 2026-07-09 — returns event
        history for status objects).
        """
        response = self._request(
            "GET",
            f"/status-feed/{feed_id}/status-objects/{object_id}/status-events",
            segment="accounts",
            correl_id=correl_id,
        )
        return StatusEventsResponse.from_dict(response.json())

    def post_status_events(
        self,
        myq_case_id: str,
        master_account: str | None = None,
        account: str | None = None,
        message: str | None = None,
        documents: list[dict] | None = None,
        status_object_id: str | None = None,
        show_account: MaskMode | None = None,
        correl_id: str | None = None,
    ) -> StatusEventsPostResponse:
        """Post a status event to an existing case.

        Sandbox: NOT VERIFIED - requires a valid myqCaseId (max 16 chars)
        from the MyQ case management system. No way to create/obtain case IDs
        via the API. Need a real case ID to test.

        Either message or documents must be provided.

        Args:
            myq_case_id: Required MyQ case id (e.g. "WI-123456").
            master_account: Optional master account scope.
            account: Optional sub-account scope.
            message: Plain-text update to append to the case.
            documents: Attachments, each ``{"name": "...", "base64EncodedFileContent": "..."}``.
            status_object_id: Optional existing status object id.
            show_account: Mask/Show in the response.
        """
        body: dict = {"myqCaseId": myq_case_id}
        if master_account:
            body["masterAccount"] = master_account
        if account:
            body["account"] = account
        if message:
            body["message"] = message
        if documents:
            body["documents"] = documents
        if status_object_id:
            body["statusObjectId"] = status_object_id
        if show_account:
            body["showAccount"] = show_account
        response = self._request(
            "POST", "/status-events", json_data=body, segment="accounts",
            correl_id=correl_id,
        )
        return StatusEventsPostResponse.from_dict(response.json())

    # =====================================================================
    # AS Transactions (segment: accounts)
    # =====================================================================

    def get_transactions(
        self,
        account: str,
        filter_start_date: str | None = None,
        filter_end_date: str | None = None,
        filter_type: str | None = None,
        filter_symbol: str | None = None,
        sort_by: str | None = None,
        sort_direction: Literal["Asc", "Desc"] | None = None,
        page_cursor: str | None = None,
        page_limit: int = 250,
        show_account: MaskMode = "Mask",
    ) -> TransactionsResponse:
        """Retrieve transactions for a specific account.

        Sandbox: VERIFIED - returns transactions with action, amounts, dates.
        Production: VERIFIED 2026-07-28, including a real multi-page
        cursor walk and the 250 cap. Prod returns no count block
        (`total_count` stays None) and adds undeclared `orderId` /
        `schwabOrderId`, which join a row to the order that produced it.

        Note: unlike most AS endpoints (max page[limit] 500), the Transactions
        endpoint caps page[limit] at 250 — a larger value is a hard 400
        ("Invalid page[limit], cannot be more than 250"). Hence the 250 default.

        Args:
            account: Account number for Schwab-Client-Ids header.
            filter_type: One of Adjustments, AtmActivity, BillPay, Checks,
                CorporateActions, Deposits, DividendsAndCapitalGains,
                ElectronicTransfers, Fees, Interest, Misc, SecurityTransfers,
                SweepTransfers, Taxes, Trades, VisaDebitCard, Withdrawals.
            filter_symbol: Filter by ticker or options symbol.
            sort_by: One of Action, Amount, Date, Description, FeesAndComm,
                Price, Quantity, Symbol.
        """
        params = self._paginated_params(
            page_cursor,
            page_limit,
            show_account=show_account,
        )
        if filter_start_date:
            params["filter[startDate]"] = filter_start_date
        if filter_end_date:
            params["filter[endDate]"] = filter_end_date
        if filter_type:
            params["filter[type]"] = filter_type
        if filter_symbol:
            params["filter[symbol]"] = filter_symbol
        if sort_by:
            params["sortBy"] = sort_by
        if sort_direction:
            params["sortDirection"] = sort_direction
        response = self._request(
            "GET", "/transactions", params=params, segment="accounts",
            extra_headers={"Schwab-Client-Ids": self._format_client_ids({"account": account})},
        )
        return TransactionsResponse.from_dict(response.json())

    def get_transaction_detail(
        self,
        account: str,
        executed_date: str,
        published_date: str,
        show_account: MaskMode = "Mask",
    ) -> TransactionDetail:
        """Retrieve detailed info for one transaction, addressed by its
        executed date + published date (the endpoint's composite key).

        Production: VERIFIED 2026-07-28.

        Per the Transactions spec, filter[executedDate] and
        filter[publishedDate] are REQUIRED — without them the endpoint
        is a hard 400, which is why the earlier paginated form of this
        method could never succeed. Source both values from a
        Transaction returned by get_transactions() (``executed_date``,
        ``published_date`` — the published date keeps its full
        timestamp, e.g. "2022-05-20T15:46:13.123456").

        Args:
            executed_date: e.g. "2022-05-20".
            published_date: e.g. "2022-05-20T15:46:13.123456".
        """
        params = {
            "filter[executedDate]": executed_date,
            "filter[publishedDate]": published_date,
            "showAccount": show_account,
        }
        response = self._request(
            "GET", "/transactions/detail", params=params, segment="accounts",
            extra_headers={"Schwab-Client-Ids": self._format_client_ids({"account": account})},
        )
        return TransactionDetail.from_dict(response.json())

    # =====================================================================
    # AS Standing Authorizations (segment: transfers)
    # =====================================================================

    def get_standing_instructions(
        self,
        master_account: str,
        account: str,
        page_cursor: str | None = None,
        page_limit: int = 500,
        show_account: MaskMode = "Mask",
    ) -> StandingInstructionsResponse:
        """Retrieve standing authorization templates.

        Sandbox + Production: VERIFIED (prod 2026-07-09 — returned a real
        ACH SLOA; sandbox now also has one instruction after months of
        empty results). Uses transfers/v1 segment. Requires BOTH
        masterAccount and account in Schwab-Client-Ids header.
        """
        params = self._paginated_params(
            page_cursor,
            page_limit,
            show_account=show_account,
        )
        response = self._request(
            "GET", "/standing-instructions", params=params, segment="transfers",
            extra_headers={
                "Schwab-Client-Ids": self._format_client_ids({"masterAccount": master_account, "account": account})
            },
        )
        return StandingInstructionsResponse.from_dict(response.json())

    def get_standing_instruction(
        self,
        instruction_id: str,
        master_account: str,
        account: str,
        show_account: MaskMode = "Mask",
    ) -> StandingInstructionDetail:
        """Retrieve full detail (incl. counter-party bank info) for a
        single standing authorization by ID.

        Sandbox + Production: VERIFIED (prod 2026-07-09, with real
        counter-party bank info) — returns a `standing-instruction-detail`
        record with the embedded counter_party object. Requires BOTH
        masterAccount and account in Schwab-Client-Ids header.

        Args:
            instruction_id: The SLOA's id from a list-endpoint summary.
            master_account: Master account scope for Schwab-Client-Ids.
            account: Sub-account scope for Schwab-Client-Ids.
        """
        response = self._request(
            "GET",
            f"/standing-instructions/{instruction_id}",
            params={"showAccount": show_account},
            segment="transfers",
            extra_headers={
                "Schwab-Client-Ids": self._format_client_ids({"masterAccount": master_account, "account": account})
            },
        )
        return StandingInstructionDetail.from_dict(response.json())

    # =====================================================================
    # AS Move Money Activity (segment: transfers)
    # =====================================================================

    def get_move_money_activities(
        self,
        account: str,
        select: Literal["Recurring", "Upcoming", "Recent"] | None = None,
        show_account: MaskMode = "Mask",
        page_limit: int | None = None,
        page_cursor: str | None = None,
        correl_id: str | None = None,
    ) -> MoveMoneyActivitiesResponse:
        """Get money-movement activity (recurring / upcoming / recent) for an
        account: scheduled transfers, wires, ACH, journals, checks.

        Sandbox: VERIFIED — returns recurring/upcoming/recent buckets.
        Production: VERIFIED 2026-07-28 against an account with real
        recurring MoneyLink transfers — buckets, select= filtering (both
        directions) and the per-bucket date fields all confirmed.
        Recurring items carry `nextTransactionDate` and NO status;
        upcoming/recent carry `transactionDate` and a status
        ("Complete"). Account discovery finds accounts that hold
        positions, not ones that move money, so the prod suite takes the
        account to probe from SCHWAB_PROD_MOVE_MONEY_ACCOUNT.

        Spec: docs/schwab-move-money-activity-openapi.json (v2.0.0).
        Note the Schwab-Client-Ids header takes the **account only**
        (``account=<n>``) — passing masterAccount (alone or with account)
        is rejected with 400 "not valid for Schwab-Client-Ids". The
        showAccount query param is spelled ``ShowAccount`` (capital S)
        in this product's spec, unlike every other AS product.

        Args:
            account: Account number for the Schwab-Client-Ids header.
            select: Restrict the response to one bucket ("Recurring",
                "Upcoming", or "Recent"); all three when omitted.
            page_limit / page_cursor: NOT in the official spec — the
                sandbox tolerates (ignores) them. Kept for backward
                compatibility; omitted from the request when None.
        """
        params: dict = {"ShowAccount": show_account}
        if select:
            params["select"] = select
        if page_limit is not None or page_cursor is not None:
            params.update(self._paginated_params(page_cursor, page_limit or 500))
        response = self._request(
            "GET", "/activities", params=params, segment="transfers",
            extra_headers={"Schwab-Client-Ids": self._format_client_ids({"account": account})},
            correl_id=correl_id,
        )
        return MoveMoneyActivitiesResponse.from_dict(response.json())

    def get_tax_withholding_elections(
        self,
        account: str,
        show_account: MaskMode = "Mask",
        correl_id: str | None = None,
    ) -> TaxWithholdingElectionsResponse:
        """Get an account's tax-withholding elections (federal/state
        percentages and opt-out flags).

        Production: VERIFIED 2026-07-28.

        Part of AS Move Money Activity v2
        (docs/schwab-move-money-activity-openapi.json). Same header
        contract as /activities: Schwab-Client-Ids takes account only.
        """
        response = self._request(
            "GET", "/tax-withholding-elections",
            params={"ShowAccount": show_account},
            segment="transfers",
            extra_headers={"Schwab-Client-Ids": self._format_client_ids({"account": account})},
            correl_id=correl_id,
        )
        return TaxWithholdingElectionsResponse.from_dict(response.json())

    # =====================================================================
    # AS Move Money Transfers (segment: transfers) — WRITES
    # =====================================================================
    #
    # These three POSTs INITIATE real money movement (spec:
    # docs/schwab-move-money-transfers-openapi.json v1.0.0). A 201 does
    # not move money by itself: it queues a request the client approves
    # via eAuthorization (Schwab Alliance). Track progress with the
    # Status API. Unlike the GET routes in this segment, the account
    # travels in the BODY — no Schwab-Client-Ids header is sent.

    def create_ach_transfer(
        self,
        standing_authorization_id: str,
        account: int | str,
        client_id: int,
        amount: float,
        process_date: str,
        second_process_date: str | None = None,
        end_date: str | None = None,
        frequency: str | None = None,
        ptrs_details: dict | None = None,
        retirement_details: dict | None = None,
        show_account: MaskMode = "Mask",
        correl_id: str | None = None,
    ) -> AchTransferResponse:
        """Initiate an ACH transfer against an existing standing
        authorization (SLOA). Returns 201 with the queued transfer.

        Args:
            standing_authorization_id: SLOA id from AS Standing
                Authorizations (ACH ids look like "A-1234567890-2021").
            account: Account number tied to the SLOA (body field).
            client_id: Schwab client id (integer) of the account holder.
            amount: Transfer amount.
            process_date: Requested processing date, "YYYY-MM-DD".
            second_process_date: Second monthly date for SEMIMTH schedules.
            end_date: Last date for a recurring schedule.
            frequency: Recurring schedule code — one of SEMIMTH, MONTHLY,
                LASTBIZ, QURTRLY, SEMIANN, ANNUALLY, WKLYMON..WKLYFRI
                (narrower than the Activity product's frequency enum).
                Omit for a one-time transfer.
            ptrs_details: PTRS trust allocation dict (incomePercentage,
                principalPercentage, trustTaxCode, trusteeIAComments,
                paidFor). Mutually exclusive with retirement_details.
            retirement_details: IRA coding dict (year, distributionReason
                or contributionTypeCode/contributionTypeSubCode,
                grossNetIndicator, taxWithholdingElectionFederal/State).
        """
        body: dict = {
            "account": int(account) if str(account).isdigit() else account,
            "clientId": client_id,
            "amount": amount,
            "processDate": process_date,
            "showAccount": show_account,
        }
        if second_process_date:
            body["secondProcessDate"] = second_process_date
        if end_date:
            body["endDate"] = end_date
        if frequency:
            body["frequency"] = frequency
        if ptrs_details:
            body["ptrsRequestDetails"] = ptrs_details
        if retirement_details:
            body["retirementRequestDetails"] = retirement_details
        response = self._request(
            "POST",
            f"/ach/standing-authorizations/{standing_authorization_id}",
            json_data=body, segment="transfers", correl_id=correl_id,
        )
        return AchTransferResponse.from_dict(response.json())

    def create_wire_transfer_from_authorization(
        self,
        standing_authorization_id: str,
        account: int | str,
        amount: float,
        process_date: str,
        transmission_note: str | None = None,
        ptrs_details: dict | None = None,
        retirement_details: dict | None = None,
        show_account: MaskMode = "Mask",
        correl_id: str | None = None,
    ) -> WireTransferResponse:
        """Initiate a wire transfer against an existing standing
        authorization (wire SLOA ids look like "W-1234567890-2021").
        Returns 201 with the queued wire. Unlike the ACH route, takes no
        clientId and no recurrence fields (wires are one-time).
        """
        body: dict = {
            "account": int(account) if str(account).isdigit() else account,
            "amount": amount,
            "processDate": process_date,
            "showAccount": show_account,
        }
        if transmission_note:
            body["transmissionNote"] = transmission_note
        if ptrs_details:
            body["ptrsRequestDetails"] = ptrs_details
        if retirement_details:
            body["retirementRequestDetails"] = retirement_details
        response = self._request(
            "POST",
            f"/wires/standing-authorizations/{standing_authorization_id}",
            json_data=body, segment="transfers", correl_id=correl_id,
        )
        return WireTransferResponse.from_dict(response.json())

    def create_wire_transfer(
        self,
        account: int | str,
        client_id: int,
        amount: float,
        process_date: str,
        aba_number: str,
        recipient_bank: dict,
        recipient: dict,
        intermediary_bank: dict | None = None,
        transmission_note: str | None = None,
        ptrs_details: dict | None = None,
        retirement_details: dict | None = None,
        show_account: MaskMode = "Mask",
        correl_id: str | None = None,
    ) -> WireTransferResponse:
        """Initiate a free-form wire (no standing authorization).
        Returns 201 with the queued wire.

        NOTE — the published spec's body field names are WRONG for the
        recipient objects (sandbox-verified 2026-07-14): the live API
        requires ``recipient`` and ``recipientBank`` (the spec says
        recipientPersonOrOrgRequest / recipientBankRequest, which the
        validator rejects with "The Recipient field is required").
        Addresses are required on both objects, and the validator can
        demand an ``intermediaryBank`` ("IntermediaryBank details are
        required for transfer via intermediary banks").

        Args:
            aba_number: 9-digit routing number of the recipient bank.
            recipient_bank: {"account", "accountName", "address": {...}}
                — address is required by the live validator.
            recipient: same-account-holder shape ({"account",
                "useModifiedAccountHolderName",
                "modifiedAccountHolderName"}) or different-holder shape
                ({"account", "accountName", "address": {...}}).
            intermediary_bank: e.g. {"abaNumber": "..."} when the route
                requires an intermediary.
        """
        body: dict = {
            "account": int(account) if str(account).isdigit() else account,
            "clientId": client_id,
            "amount": amount,
            "processDate": process_date,
            "abaNumber": aba_number,
            "recipientBank": recipient_bank,
            "recipient": recipient,
            "showAccount": show_account,
        }
        if intermediary_bank:
            body["intermediaryBank"] = intermediary_bank
        if transmission_note:
            body["transmissionNote"] = transmission_note
        if ptrs_details:
            body["ptrsRequestDetails"] = ptrs_details
        if retirement_details:
            body["retirementRequestDetails"] = retirement_details
        response = self._request(
            "POST", "/wires",
            json_data=body, segment="transfers", correl_id=correl_id,
        )
        return WireTransferResponse.from_dict(response.json())

    # =====================================================================
    # AS Feature Enrollment (segment: users)
    # =====================================================================

    def get_data_delivery_enrollment(
        self, correl_id: str | None = None
    ) -> DataDeliveryEnrollmentResponse:
        """Get data delivery enrollment status for the firm.

        Sandbox + Production: VERIFIED (prod 2026-07-09 — firm is
        enrolled). Returns enrolled: true/false.
        Uses users/v2 segment. No Schwab-Client-Ids needed (firm-level).

        Args:
            correl_id: Optional Schwab-Client-CorrelId override (pass "" to
                exercise the required-header validation path).
        """
        response = self._request(
            "GET", "/data-delivery-enrollments", segment="users",
            correl_id=correl_id,
        )
        return DataDeliveryEnrollmentResponse.from_dict(response.json())

    def update_data_delivery_enrollment(
        self, enrolled: bool, correl_id: str | None = None
    ) -> None:
        """Update data delivery enrollment. Returns 204 on success.

        Sandbox: VERIFIED - toggles enrollment and change persists. Note the
        success status is 204 No Content (the Excel scenario's "201" is
        inaccurate for this endpoint).

        Args:
            correl_id: Optional Schwab-Client-CorrelId override (pass "" to
                exercise the required-header validation path).
        """
        body = {"enrolled": enrolled}
        self._request(
            "PUT", "/data-delivery-enrollments", json_data=body, segment="users",
            correl_id=correl_id,
        )

    # =====================================================================
    # AS User Authorization (segment: users)
    # =====================================================================

    def get_user_authorizations(self) -> UserAuthorizationsResponse:
        """Get current user's authorization levels.

        Sandbox: VERIFIED - returns 22 authorization types with isAuthorized
        flags and isUserFsa (firm security admin) status.
        Uses users/v2 segment. No Schwab-Client-Ids needed.
        """
        response = self._request(
            "GET", "/authorizations", segment="users"
        )
        return UserAuthorizationsResponse.from_dict(response.json())

    # =====================================================================
    # AS Trading File Upload (segment: trading_upload)
    # =====================================================================

    # =====================================================================
    # AS Trading (segment: trading)
    # =====================================================================

    @staticmethod
    def _with_default_tax_lot(item: dict) -> dict:
        """Return the equity order item with a default taxLot on Sells.

        The live service requires transactionType.taxLot on every Sell;
        taxLotMethod "None" is accepted and defers to the account's default
        lot method. Items that are not Sells, already carry a taxLot, or
        have an unexpected shape are returned unchanged.
        """
        tx = item.get("transactionType") if isinstance(item, dict) else None
        if (
            isinstance(tx, dict)
            and tx.get("type") == "Sell"
            and "taxLot" not in tx
        ):
            return {
                **item,
                "transactionType": {**tx, "taxLot": {"taxLotMethod": "None"}},
            }
        return item

    def submit_orders(
        self,
        equity_order_items: list[dict] | None = None,
        mutual_fund_order_items: list[dict] | None = None,
        validate_only: bool = True,
        should_override_warnings: bool = False,
    ) -> OrdersResponse:
        """Submit or validate trading orders.

        Sandbox: VERIFIED - both validate_only=True and False work. Real orders
        are placed and return orderNumber. Uses trading/v1 segment.

        Each equity order item requires: clientOrderIdentifier (UUID),
        masterAccount (int), account (int), quantity (int),
        securityIdentifier: {type: "Symbol"|"CUSIP", value: str},
        transactionType: {type: "Buy"|"Sell"|"SellShort"},
        orderType: {type: "Market"|"Limit"|"Stop"|"StopLimit"|"TrailingStop",
                    market: {duration: "Day"|"GoodTillCancel"|...},
                    limit: {limitPrice: float, duration: ...}}.

        Sell items REQUIRE a transactionType.taxLot block (the live service
        rejects sells without one: "Tax information is required when
        Transaction Type is Sell" — verified sandbox 2026-08-06). If a Sell
        item has no taxLot, this method injects
        {"taxLot": {"taxLotMethod": "None"}}, which the service accepts and
        resolves to the account's default lot method. Pass an explicit
        taxLot (FIFO, LIFO, HighCost, LowCost, MinimumTax, AverageCost, or
        SpecificLot + taxLotInfoList) to override.

        Fixed-income securities are NOT tradable on this API (rejected with
        code "DO"); only equity and mutual-fund order items exist.

        Mutual-fund Buy items must carry dividendReinvestment and
        capitalGains inside transactionType.buy (alongside amountType) or
        the rules engine rejects the item with "'Capital Gains' must not
        be empty" (verified sandbox 2026-08-07). Note orderNumber comes
        back as an INT in orderResults.

        Args:
            validate_only: If True (default), validate without submitting.
                Set to False to actually submit orders.
        """
        body: dict = {
            "validateOnly": validate_only,
            "shouldOverrideWarnings": should_override_warnings,
        }
        if equity_order_items:
            body["equityOrderItems"] = [
                self._with_default_tax_lot(item) for item in equity_order_items
            ]
        if mutual_fund_order_items:
            body["mutualFundOrderItems"] = mutual_fund_order_items
        response = self._request(
            "POST", "/orders", json_data=body, segment="trading"
        )
        return OrdersResponse.from_dict(response.json())

    def cancel_and_replace_orders(
        self,
        equity_order_items: list[dict] | None = None,
        validate_only: bool = True,
        should_override_warnings: bool = False,
    ) -> OrdersResponse:
        """Cancel and replace existing equity orders.

        Sandbox: VERIFIED - returns validation results. Each order item
        must include cancelReplaceOrderNumber from the original order.
        Sell items get the same default taxLot injection as submit_orders.

        Args:
            validate_only: If True (default), validate without submitting.
        """
        body: dict = {
            "validateOnly": validate_only,
            "shouldOverrideWarnings": should_override_warnings,
        }
        if equity_order_items:
            body["equityOrderItems"] = [
                self._with_default_tax_lot(item) for item in equity_order_items
            ]
        response = self._request(
            "PUT", "/orders", json_data=body, segment="trading"
        )
        return OrdersResponse.from_dict(response.json())

    def cancel_orders(
        self,
        equity_orders: list[dict] | None = None,
        mutual_fund_orders: list[dict] | None = None,
    ) -> OrdersResponse:
        """Cancel existing orders.

        Sandbox: VERIFIED - endpoint responds (needs clientOrderIdentifier).
        Each item needs cancelOrderNumber and clientOrderIdentifier (UUID).
        """
        body: dict = {}
        if equity_orders:
            body["equityOrders"] = equity_orders
        if mutual_fund_orders:
            body["mutualFundOrders"] = mutual_fund_orders
        response = self._request(
            "DELETE", "/orders", json_data=body, segment="trading"
        )
        return OrdersResponse.from_dict(response.json())

    def get_order_status(
        self,
        account: int | str,
        from_date: str,
        to_date: str,
        master_account: int | str | None = None,
        order_status: str = "All",
        order_numbers: list[int] | None = None,
        contingent_ids: list[int] | None = None,
        symbols: list[str] | None = None,
        asset_types: list[str] | None = None,
    ) -> OrdersStatusResponse:
        """Get status of trading orders.

        Sandbox: VERIFIED - returns order details with status, enter time,
        cusip, quantity, price. Works after submitting an order.

        The ``account`` filter is INERT on the live service (verified
        2026-08-06/07): responses carry master-wide rows, including other
        tenants' fixture orders under a shared sandbox master. Filter
        client-side by account / clientOrderIdentifier and do not rely on
        ``totalOrders``.

        Args:
            order_status: One of All, Open, Filled, Canceled, Expired, Pending.
            order_numbers: Restrict to these system-generated order numbers.
            contingent_ids: Restrict to these contingent order ids.
            symbols: Restrict to these equity / mutual fund symbols.
            asset_types: Restrict to these asset types, e.g.
                ["Equity", "MutualFund"].
        """
        body: dict = {
            "account": int(account) if str(account).isdigit() else account,
            "fromDate": from_date,
            "toDate": to_date,
            "orderStatus": order_status,
        }
        if master_account not in (None, ""):
            body["masterAccount"] = (
                int(master_account)
                if str(master_account).isdigit()
                else master_account
            )
        if order_numbers:
            body["orderNumbers"] = [int(n) for n in order_numbers]
        if contingent_ids:
            body["contingentIds"] = [int(c) for c in contingent_ids]
        if symbols:
            body["symbol"] = list(symbols)
        if asset_types:
            body["assetType"] = list(asset_types)
        response = self._request(
            "POST", "/orders/status", json_data=body, segment="trading"
        )
        return OrdersStatusResponse.from_dict(response.json())

    # =====================================================================
    # AS Trading File Upload (segment: trading_upload)
    # =====================================================================

    def upload_blotters(self, base64_file_content: str) -> None:
        """Upload trade blotter file. Returns 204 on success.

        Sandbox: VERIFIED (2026-08-07) - a spec-conformant Web Trading
        trade order file is accepted with 204. File rules: comma-delimited,
        NO header row, ALL CAPS, 4-30 fields per row (Simple format is
        ACCOUNT,ACTION,QUANTITY,SYMBOL), charset limited to alphanumerics
        plus space / . + * , %. Invalid rows are dropped SILENTLY at Web
        Trading import time, so validate file conformance before upload.
        Uses trading/v2 segment.
        """
        body = {"base64EncodedFileContent": base64_file_content}
        self._request(
            "POST", "/upload-blotters", json_data=body, segment="trading_upload"
        )

    def upload_allocations(
        self,
        base64_file_content: str,
        master_account: int | str,
    ) -> None:
        """Upload allocation file. Returns 204 on success.

        Sandbox: VERIFIED (2026-08-07) - accepts ONLY the FIXED-WIDTH
        allocation format (Web Trading file spec section 4). The equally
        documented comma-delimited allocation format (section 3) is
        rejected 400 with the MISLEADING message "The file does not have a
        valid filename format" - no filename is transmitted on this API;
        the actual problem is the delimiter style. Fixed-width layout:
        header ``EH`` + date(8) + master(8, zero-padded) + action(3,
        left-just) + symbol(21, left-just) + avg price(13, %013.4f) +
        trade date(8); detail ``EA`` + sub-account + quantity(15,
        zero-padded); trailer ``ET`` + count(5) + total quantity(15).
        CRLF line endings, ALL CAPS, no UTF-8 BOM. Allocations are
        accepted on Trade Day only. Uses trading/v2 segment.
        """
        body = {
            "base64EncodedFileContent": base64_file_content,
            "masterAccount": master_account,
        }
        self._request(
            "POST", "/upload-allocations", json_data=body, segment="trading_upload"
        )

    # =====================================================================
    # High-level convenience: account-shaped facades
    # =====================================================================
    #
    # These compose multiple raw endpoints into a single call. Use them
    # when you want a quick answer; drop down to the per-API methods
    # above when you need fine control.

    def list_accounts(
        self, show_account: MaskMode = "Mask"
    ) -> list[AccountSummary]:
        """List every account the caller can see, returned as compact
        summaries (formatted_account, master_account, name, registration
        type, restriction codes).

        Walks all pages of /account-profiles (AS Account). If that
        product isn't attached to the app, falls back to Account
        Inquiry's GET /accounts — Schwab has swapped which of the two is
        attached before, and this facade must survive either state.
        Fallback summaries carry empty restriction_codes (Account
        Inquiry doesn't return them). For one or two pages this is fine;
        for very large firms it'll do multiple round trips.
        """
        try:
            profiles = self.get_all_account_profiles(show_account=show_account)
            return [AccountSummary.from_profile(p) for p in profiles]
        except httpx.HTTPStatusError as e:
            if not product_not_attached(e):
                raise
            # Fallback inside the except so a failure here chains the
            # original product-gap 401 for diagnosis.
            accounts = self.get_all_accounts(show_account=show_account)
            return [AccountSummary.from_account_info(a) for a in accounts]

    def get_account_detail(
        self,
        account: str,
        master_account: str | None = None,
        show_account: MaskMode = "Show",
    ) -> AccountDetail:
        """Pull every 1:1-with-account fact for one account, merged from
        the four contributing endpoints.

        Sources:
        - profile  ← /account-profiles (paginated; this walks pages and
          filters by `account`). When AS Account isn't attached to the
          app, the summary fields fall back to Account Inquiry's
          GET /accounts and `profile` (and `rmd`) stay None.
        - preferences_and_authorizations  ← /preferences-and-authorizations/list
          (single batched call with one account).
        - document_preferences  ← /document-preferences/list (single
          batched call; result is the matching documentPreferences entry,
          not the whole response wrapper).
        - rmd  ← /account-rmd, only if the profile says it's an IRA.

        For 1:N data (roles/beneficiaries, SLOAs) use
        get_roles_for_account / get_slas_for_account.

        show_account defaults to "Show" because most callers chain into
        downstream actions that need the unmasked ID. Passing "Mask"
        masks the strings in the P&A / document-preferences facets; the
        profile lookup itself always runs unmasked because Schwab offers
        no unmasked match key on masked pages — with a masked walk the
        account could never be found.

        The `account` parameter MUST be unmasked — Schwab rejects masked
        values in Schwab-Client-Ids headers and request bodies.

        Raises ValueError if the account isn't visible in whichever
        account product is attached (same contract as
        get_sloas_for_account's master lookup).
        """
        # Profile: walk pages until we find this account. The walk is
        # always unmasked ("Show") — matching a caller-supplied unmasked
        # account against masked page strings can never succeed. If AS
        # Account isn't attached to the app, fall back to Account Inquiry
        # for the summary-level fields (`info`); the returned
        # AccountDetail then has profile=None.
        profile = None
        info = None
        try:
            profile = self._find_paged(
                lambda c: self.get_account_profiles(
                    page_cursor=c, show_account="Show",
                ),
                lambda page: page.profiles,
                lambda p: p.formatted_account == account,
            )
        except httpx.HTTPStatusError as e:
            if not product_not_attached(e):
                raise
            info = self._find_paged(
                lambda c: self.get_accounts(page_cursor=c, show_account="Show"),
                lambda page: page.accounts,
                lambda a: a.id == account,
            )

        if profile is None and info is None:
            raise ValueError(
                f"account {account!r} not found via /account-profiles or "
                "/accounts — check the (unmasked) account number"
            )

        # P&A and document preferences accept a list of accounts in the
        # body and expose `showAccount` as a body-form param.
        pa_resp = self.get_preferences_and_authorizations(
            [account], show_account=show_account,
        )
        pa = pa_resp.items[0] if pa_resp.items else None

        doc_resp = self.get_document_preferences(
            [account], show_account=show_account,
        )
        doc = next(
            (e for e in doc_resp.document_preferences if e.formatted_account == account),
            None,
        )
        if doc is None and doc_resp.document_preferences:
            doc = doc_resp.document_preferences[0]

        # Summary-level fields come from whichever account source answered.
        src = profile or info
        formatted_account = (
            profile.formatted_account if profile is not None else info.id
        )
        formatted_master_account = src.formatted_master_account or master_account or ""
        account_name = src.title1 or src.title2 or ""
        registration_type = src.registration_type

        # RMD only applies to retirement accounts. Skip the call entirely
        # for non-retirement accounts to avoid pointless pagination.
        # Schwab returns either full names ("Roth IRA", "Traditional IRA")
        # or two-char codes (RO, IR, SE, SI, IH) depending on the
        # endpoint's response shape. Cover both. /account-rmd rides the
        # same AS Account product as /account-profiles, so when that
        # product isn't attached the RMD facet degrades to None.
        rmd = None
        rt = registration_type or ""
        looks_like_ira = (
            "ira" in rt.lower()
            or "roth" in rt.lower()
            or rt.upper() in {"RO", "IR", "SE", "SI", "IH"}
        )
        if looks_like_ira:
            try:
                rmd = self._find_paged(
                    lambda c: self.get_account_rmd(
                        page_cursor=c, show_account="Show",
                    ),
                    lambda page: page.rmds,
                    lambda r: r.formatted_account == account,
                )
            except httpx.HTTPStatusError as e:
                if not product_not_attached(e):
                    raise

        return AccountDetail(
            formatted_account=formatted_account,
            formatted_master_account=formatted_master_account,
            account_name=account_name,
            registration_type=registration_type,
            profile=profile,
            preferences_and_authorizations=pa,
            document_preferences=doc,
            rmd=rmd,
        )

    def get_roles_for_account(
        self,
        account: str,
        show_account: MaskMode = "Show",
        show_dob: MaskMode = "Mask",
        show_tax_id: MaskMode = "Mask",
    ) -> list[Role]:
        """All Role records (beneficiaries + holders + advisor roles)
        for a single account. Walks pages of /account-roles internally.

        show_account=Show is the default because the Role.account_holder_id
        in the response is the typical input to a follow-up
        get_account_holder() call, which requires an unmasked account in
        its Schwab-Client-Ids header.
        """
        ar = self._find_paged(
            lambda c: self.get_account_roles(
                page_cursor=c,
                show_account=show_account,
                show_dob=show_dob,
                show_tax_id=show_tax_id,
            ),
            lambda page: page.account_roles,
            lambda ar: ar.formatted_account == account,
        )
        return list(ar.roles) if ar is not None else []

    def get_sloas_for_account(
        self,
        account: str,
        master_account: str | None = None,
        show_account: MaskMode = "Show",
    ) -> list[StandingInstruction]:
        """All standing letters of authorization (SLOAs) for one account.
        Thin wrapper around get_standing_instructions() that returns the
        list directly for ergonomic chaining.

        If master_account is omitted, this method walks /account-profiles
        to find the master for the given account. That's one extra round
        trip; pass master_account explicitly if you already have it.
        """
        if master_account is None:
            master_account = self._lookup_master_account(account)
        resp = self.get_standing_instructions(
            master_account, account, show_account=show_account,
        )
        return list(resp.instructions)

    def _lookup_master_account(self, account: str) -> str:
        """Find the master_account for a given formatted account by
        walking /account-profiles, falling back to Account Inquiry's
        GET /accounts when that product isn't attached. Used by facade
        methods that take master_account as optional. Raises ValueError
        if not found."""
        try:
            p = self._find_paged(
                lambda c: self.get_account_profiles(
                    page_cursor=c, show_account="Show",
                ),
                lambda page: page.profiles,
                lambda p: p.formatted_account == account,
            )
            if p is not None:
                return p.formatted_master_account
        except httpx.HTTPStatusError as e:
            if not product_not_attached(e):
                raise
            a = self._find_paged(
                lambda c: self.get_accounts(page_cursor=c, show_account="Show"),
                lambda page: page.accounts,
                lambda a: a.id == account,
            )
            if a is not None:
                return a.formatted_master_account
        raise ValueError(
            f"account {account!r} not found via /account-profiles or "
            "/accounts; pass master_account explicitly"
        )
