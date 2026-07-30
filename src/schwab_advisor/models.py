"""Data models for Schwab Advisor API responses."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

# Schwab Advisor Center deep-link template for an individual alert.
# The si2 UI takes (alertId, tab=alerts, display=details, index=0) and lands
# directly on the alert detail page when the user clicks through. Verified
# 2026-05-07 against a real prod alert.
SAC_ALERT_URL_TEMPLATE = (
    "https://si2.schwabinstitutional.com/SI2/Home/default.aspx"
    "?display=details&index=0&alertId={alert_id}&tab=alerts"
)


def sac_alert_url(alert_id: int | str) -> str:
    """Build a Schwab Advisor Center deep-link for an alert.

    Empty/falsy alert ids return an empty string so this is safe to call
    on partially-populated dataclass instances.
    """
    if not alert_id and alert_id != 0:
        return ""
    return SAC_ALERT_URL_TEMPLATE.format(alert_id=alert_id)


@dataclass
class TokenResponse:
    """OAuth token response from Schwab API."""

    access_token: str
    refresh_token: str
    token_type: str  # "Bearer"
    expires_in: int  # seconds
    scope: str
    expires_at: datetime  # calculated from expires_in

    def is_expired(self, margin_seconds: int = 60) -> bool:
        """Check if the access token has expired (or will within margin).

        expires_at is stamped after the token round trip, so it already
        overstates the real lifetime by the request latency; the margin
        keeps a token that expires mid-request from surfacing as a 401.
        """
        return datetime.now() >= self.expires_at - timedelta(
            seconds=margin_seconds
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_type": self.token_type,
            "expires_in": self.expires_in,
            "scope": self.scope,
            "expires_at": self.expires_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TokenResponse":
        """Create TokenResponse from dictionary."""
        return cls(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            token_type=data["token_type"],
            expires_in=data["expires_in"],
            scope=data["scope"],
            expires_at=datetime.fromisoformat(data["expires_at"]),
        )


# --- Pagination helpers ---


def _parse_meta(data: dict) -> tuple[str | None, int | None]:
    """Extract next_cursor and total record count from JSON:API meta.

    Schwab returns nextCursor="" (empty string) when pagination is exhausted
    (per OpenAPI spec). Normalize that to None so callers have a single
    "no more pages" signal: ``if resp.next_cursor is None``.

    `meta.count.actual` is the per-page record count, not the grand total —
    the field response models call `total_count` should be the grand total
    `meta.count.total`, which Schwab only populates when the request sent
    `includeTotalCount=true`. Returns None when total wasn't requested.
    """
    meta = data.get("meta") or {}
    paging = meta.get("paging") or {}
    count = meta.get("count") or {}
    next_cursor = paging.get("nextCursor") or None
    return next_cursor, count.get("total")


# --- Null-safe unwrap/coercion helpers ---
#
# Schwab payloads are inconsistent: "data" may be a list, a single object,
# null, or absent; any attribute may be explicitly null (so .get defaults
# don't fire). These helpers are the single place that leniency lives;
# tests/test_models_robustness.py sweeps every model against the
# adversarial shapes.


def _data_list(data: dict) -> list[dict]:
    """The "data" member as a list of dicts: null -> [], single object
    -> [obj] (Schwab returns both shapes for some endpoints), non-dict
    entries dropped."""
    d = data.get("data") if isinstance(data, dict) else None
    if d is None:
        return []
    if isinstance(d, dict):
        return [d]
    return [x for x in d if isinstance(x, dict)]


def _unwrap_data(data: dict) -> dict:
    """The "data" member as a single dict: null/absent -> {}, a list
    wrapper -> its first dict element (some detail endpoints wrap)."""
    d = data.get("data") if isinstance(data, dict) else None
    if isinstance(d, list):
        d = next((x for x in d if isinstance(x, dict)), None)
    return d if isinstance(d, dict) else {}


def _safe_float(data: dict, key: str, default: float = 0.0) -> float:
    """Coerce a JSON numeric field to float; tolerate strings and None."""
    v = data.get(key)
    if v is None or v == "":
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _safe_int(data: dict, key: str, default: int = 0) -> int:
    """Coerce a JSON numeric field to int; tolerate strings and None."""
    v = data.get(key)
    if v is None or v == "":
        return default
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


# --- Account Profiles (AS Account) ---


@dataclass
class Address:
    """Mailing or physical address."""

    address_line1: str = ""
    address_line2: str = ""
    address_line3: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""
    country: str = ""
    address_type: str = ""
    is_international: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> "Address":
        return cls(
            address_line1=(data.get("addressLine1") or ""),
            address_line2=(data.get("addressLine2") or ""),
            address_line3=(data.get("addressLine3") or ""),
            city=(data.get("city") or ""),
            state=(data.get("state") or ""),
            zip_code=(data.get("zipCode") or ""),
            country=(data.get("country") or ""),
            address_type=(data.get("addressType") or ""),
            is_international=bool(data.get("isInternational") or False),
        )


@dataclass
class AccountProfile:
    """Account profile from /account-profiles. Parses the full
    26-field OpenAPI schema. Note: many of the prefs/sweep/options
    fields are duplicated on /preferences-and-authorizations/list — same
    data, two endpoints; either is sufficient."""

    formatted_account: str = ""
    formatted_master_account: str = ""
    master_accounts: list[dict] = field(default_factory=list)
    registration_type: str = ""
    title1: str = ""
    title2: str = ""
    title3: str = ""
    established_date: str = ""
    last_updated_date: str = ""
    email: str = ""
    home_phone: str = ""
    business_phone: str = ""
    mailing_address: Address | None = None
    is_money_link_enabled: bool = False
    is_margin_enabled: bool = False
    approved_options_level: str = ""
    enrolled_in_schwab_bill_pay: bool = False
    is_client_check_writing_enabled: bool = False
    cash_sweep_fund: str = ""
    interest_dividends_cash_frequency: str = ""
    proceeds_cash_frequency: str = ""
    interest_dividends_margin_frequency: str = ""
    proceeds_margin_frequency: str = ""
    is_fee_payment_authorized: bool = False
    restriction_codes: list[str] = field(default_factory=list)
    document_delivery_options: list[dict] = field(default_factory=list)
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "AccountProfile":
        """Create from JSON:API data item (with id/type/attributes)."""
        attrs = (data.get("attributes") or data)
        addr = attrs.get("mailingAddress")
        return cls(
            formatted_account=(attrs.get("formattedAccount") or ""),
            formatted_master_account=(attrs.get("formattedMasterAccount") or ""),
            master_accounts=(attrs.get("masterAccounts") or []),
            registration_type=(attrs.get("accountRegistrationType") or ""),
            title1=(attrs.get("accountTitle1") or ""),
            title2=(attrs.get("accountTitle2") or ""),
            title3=(attrs.get("accountTitle3") or ""),
            established_date=(attrs.get("establishedDate") or ""),
            last_updated_date=(attrs.get("lastUpdatedDate") or ""),
            email=(attrs.get("emailAddress") or ""),
            home_phone=(attrs.get("homePhone") or ""),
            business_phone=(attrs.get("businessPhone") or ""),
            mailing_address=Address.from_dict(addr) if addr else None,
            is_money_link_enabled=bool(attrs.get("isMoneyLinkEnabled") or False),
            is_margin_enabled=bool(attrs.get("isMarginEnabled") or False),
            approved_options_level=(attrs.get("approvedOptionsLevel") or ""),
            enrolled_in_schwab_bill_pay=bool(attrs.get("enrolledInSchwabBillPay") or False),
            is_client_check_writing_enabled=attrs.get(
                "isClientCheckWritingEnabled", False
            ),
            cash_sweep_fund=(attrs.get("cashSweepFund") or ""),
            interest_dividends_cash_frequency=attrs.get(
                "interestDividendsCashFrequency", ""
            ),
            proceeds_cash_frequency=(attrs.get("proceedsCashFrequency") or ""),
            interest_dividends_margin_frequency=attrs.get(
                "interestDividendsMarginFrequency", ""
            ),
            proceeds_margin_frequency=(attrs.get("proceedsMarginFrequency") or ""),
            is_fee_payment_authorized=attrs.get(
                "isFeePaymentAuthorizationEnabled", False
            ),
            restriction_codes=(attrs.get("restrictionCodes") or []),
            document_delivery_options=(attrs.get("documentDeliveryOptions") or []),
            raw_data=data,
        )


@dataclass
class AccountProfilesResponse:
    """Response from /account-profiles."""

    profiles: list[AccountProfile]
    next_cursor: str | None = None
    total_count: int | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "AccountProfilesResponse":
        profiles = [AccountProfile.from_dict(p) for p in _data_list(data)]
        next_cursor, count = _parse_meta(data)
        return cls(profiles=profiles, next_cursor=next_cursor, total_count=count)


# --- Alerts ---


def _parse_alert_attrs(data: dict) -> dict:
    """Parse common alert fields from a JSON:API item."""
    attrs = (data.get("attributes") or data)
    alert_id = (data.get("id") or "")
    return {
        "id": alert_id,
        "formatted_account": (attrs.get("formattedAccount") or ""),
        "formatted_master_account": (attrs.get("formattedMasterAccount") or ""),
        "account_title": (attrs.get("accountTitle") or ""),
        "account_description": (attrs.get("accountDescription") or ""),
        "category": (attrs.get("category") or ""),
        "type_code": (attrs.get("typeCode") or ""),
        "alert_type": (attrs.get("type") or ""),
        "subject": (attrs.get("subject") or ""),
        "text": (attrs.get("text") or ""),
        "status": (attrs.get("status") or ""),
        "created_date": (attrs.get("createdDate") or ""),
        "source": (attrs.get("source") or ""),
        "external_system_ref_id": (attrs.get("externalSystemRefId") or ""),
        "from_name": (attrs.get("fromName") or ""),
        "priority": (attrs.get("priority") or ""),
        "reply_type": (attrs.get("replyType") or ""),
        "destination": (attrs.get("destination") or ""),
        "viewed_date": (attrs.get("viewedDate") or ""),
        "transfer_status": (attrs.get("transferStatus") or ""),
        "transfer_status_date": (attrs.get("transferStatusDate") or ""),
        "is_archived": bool(attrs.get("isArchived") or False),
        "is_restricted": bool(attrs.get("isRestricted") or False),
        "is_copied": bool(attrs.get("isCopied") or False),
        "sac_url": sac_alert_url(alert_id),
        "raw_data": data,
    }


@dataclass
class Alert:
    """Alert from /alerts."""

    id: int | str = ""
    formatted_account: str = ""
    formatted_master_account: str = ""
    account_title: str = ""
    account_description: str = ""
    category: str = ""
    type_code: str = ""
    alert_type: str = ""
    subject: str = ""
    text: str = ""
    status: str = ""
    created_date: str = ""
    source: str = ""
    external_system_ref_id: str = ""
    from_name: str = ""
    priority: str = ""
    reply_type: str = ""
    destination: str = ""
    viewed_date: str = ""
    transfer_status: str = ""
    transfer_status_date: str = ""
    is_archived: bool = False
    is_restricted: bool = False
    is_copied: bool = False
    # Deep-link to the alert in Schwab Advisor Center (si2). Synthesized
    # from the alert id at parse time; not present in the Schwab response.
    sac_url: str = ""
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "Alert":
        return cls(**_parse_alert_attrs(data))


@dataclass
class AlertsResponse:
    """Response from /alerts."""

    alerts: list[Alert]
    next_cursor: str | None = None
    total_count: int | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "AlertsResponse":
        alerts = [Alert.from_dict(a) for a in _data_list(data)]
        next_cursor, count = _parse_meta(data)
        return cls(alerts=alerts, next_cursor=next_cursor, total_count=count)


# --- Transactions ---


@dataclass
class Transaction:
    """Transaction from /transactions."""

    id: str = ""
    formatted_account: str = ""
    type_code: str = ""
    action: str = ""
    description: str = ""
    security_type: str = ""
    symbol: str = ""
    cusip_number: str = ""
    check_number: str = ""
    # SPEC DRIFT: prod returns orderId + schwabOrderId on trade rows,
    # neither declared in the Transactions spec (verified 2026-07-28).
    # They join a transaction to the order that produced it.
    order_id: int = 0
    schwab_order_id: int = 0
    trade_date: str = ""
    settle_date: str = ""
    executed_date: str = ""
    published_date: str = ""
    quantity: float = 0.0
    price: float = 0.0
    amount: float = 0.0
    net_amount: float = 0.0
    fees_and_comm: float = 0.0
    exchange_processing_fee: float = 0.0
    order_handling_fee: float = 0.0
    redemption_fee: float = 0.0
    is_intraday: bool = False
    has_details: bool = False
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "Transaction":
        attrs = (data.get("attributes") or data)
        return cls(
            id=(data.get("id") or ""),
            formatted_account=(attrs.get("formattedAccount") or ""),
            type_code=(attrs.get("typeCode") or ""),
            action=(attrs.get("action") or ""),
            description=(attrs.get("description") or ""),
            security_type=(attrs.get("securityType") or ""),
            symbol=(attrs.get("symbol") or ""),
            cusip_number=(attrs.get("cusipNumber") or ""),
            check_number=(attrs.get("checkNumber") or ""),
            order_id=_safe_int(attrs, "orderId"),
            schwab_order_id=_safe_int(attrs, "schwabOrderId"),
            trade_date=(attrs.get("tradeDate") or ""),
            settle_date=(attrs.get("settleDate") or ""),
            executed_date=(attrs.get("executedDate") or ""),
            published_date=(attrs.get("publishedDate") or ""),
            quantity=_safe_float(attrs, "quantity"),
            price=_safe_float(attrs, "price"),
            amount=_safe_float(attrs, "amount"),
            net_amount=_safe_float(attrs, "netAmount"),
            fees_and_comm=_safe_float(attrs, "feesAndComm"),
            exchange_processing_fee=_safe_float(attrs, "exchangeProcessingFee"),
            order_handling_fee=_safe_float(attrs, "orderHandlingFee"),
            redemption_fee=_safe_float(attrs, "redemptionFee"),
            is_intraday=bool(attrs.get("isIntraday") or False),
            has_details=bool(attrs.get("hasDetails") or False),
            raw_data=data,
        )


@dataclass
class TransactionsResponse:
    """Response from /transactions."""

    transactions: list[Transaction]
    next_cursor: str | None = None
    total_count: int | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "TransactionsResponse":
        txns = [Transaction.from_dict(t) for t in _data_list(data)]
        next_cursor, count = _parse_meta(data)
        return cls(transactions=txns, next_cursor=next_cursor, total_count=count)


@dataclass
class TransactionDetail:
    """Single transaction-detail record from GET /transactions/detail.

    Unlike the /transactions list (data: [...]), the detail endpoint
    returns ONE record (data: {...}) addressed by executedDate +
    publishedDate, with a richer fee/tax breakdown.
    """

    id: str = ""
    formatted_account: str = ""
    action_code: str = ""
    security_type: str = ""
    symbol: str = ""
    cusip_number: str = ""
    security_number: int = 0
    order_id: int = 0
    schwab_order_id: int = 0
    description: str = ""
    history_message: str = ""
    quantity: float = 0.0
    price: float = 0.0
    amount: float = 0.0
    net_amount: float = 0.0
    accrued_interest: float = 0.0
    commission: float = 0.0
    prime_broker_fee: float = 0.0
    trade_away_fee: float = 0.0
    order_handling_fee: float = 0.0
    redemption_fee: float = 0.0
    security_fee: float = 0.0
    state_tax: float = 0.0
    withholding_tax: float = 0.0
    other_amount: float = 0.0
    executed_date: str = ""
    settle_date: str = ""
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "TransactionDetail":
        d = data.get("data", data)
        if not isinstance(d, dict):
            d = _unwrap_data(data)
        attrs = (d.get("attributes") or d)
        return cls(
            id=(d.get("id") or ""),
            formatted_account=(attrs.get("formattedAccount") or ""),
            action_code=(attrs.get("actionCode") or ""),
            security_type=(attrs.get("securityType") or ""),
            symbol=(attrs.get("symbol") or ""),
            cusip_number=(attrs.get("cusipNumber") or ""),
            security_number=_safe_int(attrs, "securityNumber"),
            order_id=_safe_int(attrs, "orderId"),
            schwab_order_id=_safe_int(attrs, "schwabOrderId"),
            description=(attrs.get("description") or ""),
            history_message=(attrs.get("historyMessage") or ""),
            quantity=_safe_float(attrs, "quantity"),
            price=_safe_float(attrs, "price"),
            amount=_safe_float(attrs, "amount"),
            net_amount=_safe_float(attrs, "netAmount"),
            accrued_interest=_safe_float(attrs, "accruedInterest"),
            commission=_safe_float(attrs, "commission"),
            prime_broker_fee=_safe_float(attrs, "primeBrokerFee"),
            trade_away_fee=_safe_float(attrs, "tradeAwayFee"),
            order_handling_fee=_safe_float(attrs, "orderHandlingFee"),
            redemption_fee=_safe_float(attrs, "redemptionFee"),
            security_fee=_safe_float(attrs, "securityFee"),
            state_tax=_safe_float(attrs, "stateTax"),
            withholding_tax=_safe_float(attrs, "withholdingTax"),
            other_amount=_safe_float(attrs, "otherAmount"),
            executed_date=(attrs.get("executedDate") or ""),
            settle_date=(attrs.get("settleDate") or ""),
            raw_data=data,
        )


# --- Standing Instructions (SLOA) ---


@dataclass
class CounterPartyAddress:
    """Counter-party (bank) address from a SLOA detail.

    The AS Standing Authorizations spec uses different field names than
    the regular Address model: `address1/2/3` and `countryCode` instead
    of `addressLine1/2/3/4`, `city`, `state`, etc. The address3 line
    can carry city/state/zip/country mashed together (per the spec —
    the upstream UI enforces format, the API doesn't).
    """

    address1: str = ""
    address2: str = ""
    address3: str = ""
    country_code: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "CounterPartyAddress":
        return cls(
            address1=(data.get("address1") or ""),
            address2=(data.get("address2") or ""),
            address3=(data.get("address3") or ""),
            country_code=(data.get("countryCode") or ""),
        )


@dataclass
class CounterParty:
    """Counter-party (bank) on a Standing Authorization detail.

    Only populated by the singular detail endpoint
    /standing-instructions/{id}; the list endpoint returns summary
    records without counter-party information.
    """

    routing_number: str = ""
    account_number: str = ""
    name: str = ""
    bank_name: str = ""
    address: CounterPartyAddress | None = None
    phone: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "CounterParty":
        addr = data.get("address")
        return cls(
            routing_number=data.get("routingNumber", "") or "",
            account_number=data.get("accountNumber", "") or "",
            name=data.get("name", "") or "",
            bank_name=data.get("bankName", "") or "",
            address=CounterPartyAddress.from_dict(addr) if addr else None,
            phone=data.get("phone", "") or "",
        )


@dataclass
class StandingInstruction:
    """Standing-instruction summary from the list endpoint
    /standing-instructions. Each summary carries the SLOA's id, the
    account/master account it belongs to, and the embedded
    `instructions` block (nickname, transactionType, direction, IA
    auth flag).

    To get the counter-party bank info (routing, account#, name,
    address) use get_standing_instruction(id, master, account) —
    that returns the typed StandingInstructionDetail.
    """

    id: str = ""
    master_account: str = ""
    account: str = ""
    nickname: str = ""
    transaction_type: str = ""  # e.g. "J" (journal), "A" (ACH), "W" (wire), "C" (check)
    direction: str = ""  # "Outgoing" / "Incoming"
    has_ia_authority: bool = False
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "StandingInstruction":
        attrs = (data.get("attributes") or data)
        instructions = attrs.get("instructions", {}) or {}
        return cls(
            id=str((data.get("id") or "")),
            master_account=str((attrs.get("masterAccount") or "")),
            account=str((attrs.get("account") or "")),
            nickname=instructions.get("nickname", "") or "",
            transaction_type=instructions.get("transactionType", "") or "",
            direction=instructions.get("direction", "") or "",
            has_ia_authority=bool(instructions.get("hasIaAuthority") or False),
            raw_data=data,
        )


@dataclass
class StandingInstructionDetail:
    """Full SLOA record from /standing-instructions/{id}, including
    the counter-party (bank) info absent from the list endpoint."""

    id: str = ""
    master_account: str = ""
    account: str = ""
    nickname: str = ""
    transaction_type: str = ""
    direction: str = ""
    has_ia_authority: bool = False
    counter_party: CounterParty | None = None
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "StandingInstructionDetail":
        # /standing-instructions/{id} returns `data` as a single object.
        # Tolerate both that and a bare attributes-dict for defensive parsing.
        d = data.get("data", data)
        if isinstance(d, list):
            d = d[0] if d else {}
        attrs = (d.get("attributes") or d) if isinstance(d, dict) else {}
        instructions = attrs.get("instructions", {}) or {}
        cp = instructions.get("counterParty")
        return cls(
            id=str((d.get("id") or "") if isinstance(d, dict) else ""),
            master_account=str((attrs.get("masterAccount") or "")),
            account=str((attrs.get("account") or "")),
            nickname=instructions.get("nickname", "") or "",
            transaction_type=instructions.get("transactionType", "") or "",
            direction=instructions.get("direction", "") or "",
            has_ia_authority=bool(instructions.get("hasIaAuthority") or False),
            counter_party=CounterParty.from_dict(cp) if cp else None,
            raw_data=data,
        )


@dataclass
class StandingInstructionsResponse:
    """Response from /standing-instructions (list)."""

    instructions: list[StandingInstruction]
    next_cursor: str | None = None
    total_count: int | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "StandingInstructionsResponse":
        items = [StandingInstruction.from_dict(i) for i in _data_list(data)]
        next_cursor, count = _parse_meta(data)
        return cls(instructions=items, next_cursor=next_cursor, total_count=count)


# --- Profiles (account holders) ---


@dataclass
class Employment:
    """Account holder employment info."""

    employment_status: str = ""
    employer_name: str = ""
    occupation: str = ""
    industry: str = ""
    years_employed: str = ""
    publicly_traded_company: str = ""
    is_employed_by_security_or_broker_firm: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> "Employment":
        return cls(
            employment_status=(data.get("employmentStatus") or ""),
            employer_name=(data.get("employerName") or ""),
            occupation=(data.get("occupation") or ""),
            industry=(data.get("industry") or ""),
            years_employed=(data.get("yearsEmployed") or ""),
            publicly_traded_company=(data.get("publiclyTradedCompany") or ""),
            is_employed_by_security_or_broker_firm=data.get(
                "isEmployedBySecurityOrBrokerFirm", False
            ),
        )


@dataclass
class AccountHolder:
    """Account holder from /profiles/account-holders.

    Parses every documented field; downstream consumers may rely on
    completeness, so a regression that drops a field is a bug.
    """

    role: str = ""
    name: str = ""
    formatted_account: str = ""
    first_name: str = ""
    middle_name: str = ""
    last_name: str = ""
    date_of_birth: str = ""
    formatted_taxpayer_id: str = ""
    email_address: str = ""
    home_phone: str = ""
    mobile_phone: str = ""
    business_phone: str = ""
    mailing_address: Address | None = None
    citizenship: str = ""
    country_of_residence: str = ""
    alliance_web_access: str = ""
    alliance_invitation_date: str = ""
    mobile_access: str = ""
    is_trust_account: bool = False
    employment: Employment | None = None
    accounts: list[dict] = field(default_factory=list)
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "AccountHolder":
        attrs = (data.get("attributes") or data)
        addr = attrs.get("mailingAddress")
        emp = attrs.get("employment")
        return cls(
            role=(attrs.get("role") or ""),
            name=(attrs.get("name") or ""),
            formatted_account=(attrs.get("formattedAccount") or ""),
            first_name=(attrs.get("firstName") or ""),
            middle_name=(attrs.get("middleName") or ""),
            last_name=(attrs.get("lastName") or ""),
            date_of_birth=(attrs.get("formattedDateOfBirth") or ""),
            formatted_taxpayer_id=(attrs.get("formattedTaxpayerId") or ""),
            email_address=(attrs.get("emailAddress") or ""),
            home_phone=(attrs.get("homePhone") or ""),
            mobile_phone=(attrs.get("mobilePhone") or ""),
            business_phone=(attrs.get("businessPhone") or ""),
            mailing_address=Address.from_dict(addr) if addr else None,
            citizenship=(attrs.get("citizenship") or ""),
            country_of_residence=(attrs.get("countryOfResidence") or ""),
            alliance_web_access=(attrs.get("allianceWebAccess") or ""),
            alliance_invitation_date=(attrs.get("allianceInvitationDate") or ""),
            mobile_access=(attrs.get("mobileAccess") or ""),
            is_trust_account=bool(attrs.get("isTrustAccount") or False),
            employment=Employment.from_dict(emp) if emp else None,
            accounts=attrs.get("accounts") or [],
            raw_data=data,
        )


@dataclass
class AccountHoldersResponse:
    """Response from /profiles/account-holders."""

    holders: list[AccountHolder]
    next_cursor: str | None = None
    total_count: int | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "AccountHoldersResponse":
        # /profiles/account-holders returns a single object under `data`;
        # the paginated /profiles endpoints return a list. Normalize both.
        raw = _data_list(data)
        if isinstance(raw, dict):
            raw = [raw]
        holders = [AccountHolder.from_dict(h) for h in raw]
        next_cursor, count = _parse_meta(data)
        return cls(holders=holders, next_cursor=next_cursor, total_count=count)


# --- Preferences and Authorizations ---


@dataclass
class AccountPreferences:
    """Per-account feature flags + cash-sweep config."""

    is_prime_broker_enabled: bool = False
    is_margin_enabled: bool = False
    enrolled_in_schwab_bill_pay: bool = False
    cash_sweep_fund: str = ""
    is_money_link_enabled: bool = False
    approved_options_level: str = ""
    is_client_check_writing_enabled: bool = False
    demand_deposit_account: str = ""
    alliance_web_view: str = ""
    # SPEC DRIFT: prod returns marginType alongside isMarginEnabled;
    # the P&A spec declares neither it nor masterAccounts below
    # (verified 2026-07-28, once the wrapper-shape bug stopped hiding
    # the real records).
    margin_type: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "AccountPreferences":
        return cls(
            is_prime_broker_enabled=bool(data.get("isPrimeBrokerEnabled") or False),
            is_margin_enabled=bool(data.get("isMarginEnabled") or False),
            enrolled_in_schwab_bill_pay=bool(data.get("enrolledInSchwabBillPay") or False),
            cash_sweep_fund=(data.get("cashSweepFund") or ""),
            is_money_link_enabled=bool(data.get("isMoneyLinkEnabled") or False),
            approved_options_level=(data.get("approvedOptionsLevel") or ""),
            is_client_check_writing_enabled=data.get(
                "isClientCheckWritingEnabled", False
            ),
            demand_deposit_account=(data.get("demandDepositAccount") or ""),
            alliance_web_view=(data.get("allianceWebView") or ""),
            margin_type=(data.get("marginType") or ""),
        )


@dataclass
class CashAndMarginPreferences:
    """Interest/dividend/proceeds payout-frequency preferences."""

    interest_dividends_cash_frequency: str = ""
    proceeds_cash_frequency: str = ""
    interest_dividends_margin_frequency: str = ""
    proceeds_margin_frequency: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "CashAndMarginPreferences":
        return cls(
            interest_dividends_cash_frequency=data.get(
                "interestDividendsCashFrequency", ""
            ),
            proceeds_cash_frequency=(data.get("proceedsCashFrequency") or ""),
            interest_dividends_margin_frequency=data.get(
                "interestDividendsMarginFrequency", ""
            ),
            proceeds_margin_frequency=(data.get("proceedsMarginFrequency") or ""),
        )


@dataclass
class Authorizations:
    """Trade/disbursement/fee authorizations + restrictionCodes."""

    is_trading_authorization_enabled: bool = False
    disbursement_authorization: str = ""
    is_fee_payment_authorization_enabled: bool = False
    restriction_codes: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "Authorizations":
        return cls(
            is_trading_authorization_enabled=data.get(
                "isTradingAuthorizationEnabled", False
            ),
            disbursement_authorization=(data.get("disbursementAuthorization") or ""),
            is_fee_payment_authorization_enabled=data.get(
                "isFeePaymentAuthorizationEnabled", False
            ),
            restriction_codes=(data.get("restrictionCodes") or ""),
        )


@dataclass
class PreferencesAndAuthorizations:
    """Account preferences + authorizations bundle from
    /preferences-and-authorizations/list."""

    formatted_account: str = ""
    account_preferences: AccountPreferences | None = None
    cash_and_margin_preferences: CashAndMarginPreferences | None = None
    authorizations: Authorizations | None = None
    # SPEC DRIFT: undeclared in the P&A spec, returned by BOTH sandbox and
    # prod (verified 2026-07-28). Element shape is not documented, so it
    # passes through as-is rather than being typed on a guess.
    master_accounts: list = field(default_factory=list)
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "PreferencesAndAuthorizations":
        attrs = (data.get("attributes") or data)
        ap = attrs.get("accountPreferences")
        cmp_ = attrs.get("cashAndMarginPreferences")
        au = attrs.get("authorizations")
        return cls(
            formatted_account=(attrs.get("formattedAccount") or ""),
            account_preferences=AccountPreferences.from_dict(ap) if ap else None,
            cash_and_margin_preferences=(
                CashAndMarginPreferences.from_dict(cmp_) if cmp_ else None
            ),
            authorizations=Authorizations.from_dict(au) if au else None,
            master_accounts=(
                ma if isinstance(ma := attrs.get("masterAccounts"), list) else []
            ),
            raw_data=data,
        )


@dataclass
class PreferencesAndAuthorizationsResponse:
    """Response from /preferences-and-authorizations/list.

    Two shapes in the wild, and the model must handle both per ELEMENT:
    the spec (and production) return ONE data object whose attributes
    carry a nested ``preferencesAndAuthorizations`` list plus ``errors``;
    the sandbox returns the records as JSON:API array elements directly.

    Before v0.3.0 the wrapper form silently produced a single EMPTY item
    — `_data_list` normalizes a lone data object into a one-element list,
    so the nested branch below was unreachable and every real preference
    was dropped. Prod drift reporting is what surfaced it.
    """

    items: list[PreferencesAndAuthorizations]
    errors: list[dict] = field(default_factory=list)
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "PreferencesAndAuthorizationsResponse":
        items: list[PreferencesAndAuthorizations] = []
        errors: list[dict] = []
        for element in _data_list(data):
            attrs = (element.get("attributes") or element)
            if not isinstance(attrs, dict):
                continue
            nested = attrs.get("preferencesAndAuthorizations")
            element_errors = attrs.get("errors")
            if isinstance(element_errors, list):
                errors.extend(e for e in element_errors if isinstance(e, dict))
            if isinstance(nested, list):
                items.extend(
                    PreferencesAndAuthorizations.from_dict(i)
                    for i in nested
                    if isinstance(i, dict)
                )
            else:
                items.append(PreferencesAndAuthorizations.from_dict(element))
        return cls(items=items, errors=errors, raw_data=data)


# --- Alert Detail / Archive / Update responses ---


@dataclass
class StatusHistoryEntry:
    """One entry in an AlertDetail.status_history (OpenAPI StatusHistory)."""

    status: str = ""
    status_date: str = ""
    formatted_master_account: str = ""
    user_id: str = ""
    last_name: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "StatusHistoryEntry":
        return cls(
            status=(data.get("status") or ""),
            status_date=(data.get("statusDate") or ""),
            formatted_master_account=(data.get("formattedMasterAccount") or ""),
            user_id=(data.get("userId") or ""),
            last_name=(data.get("lastName") or ""),
        )


@dataclass
class AlertDetail:
    """Detailed alert from /alerts/detail/{alert_id}."""

    id: int | str = ""
    formatted_account: str = ""
    formatted_master_account: str = ""
    account_title: str = ""
    account_description: str = ""
    category: str = ""
    type_code: str = ""
    alert_type: str = ""
    subject: str = ""
    text: str = ""
    detail_text: str = ""
    detail_type: str = ""
    status: str = ""
    created_date: str = ""
    source: str = ""
    external_system_ref_id: str = ""
    from_name: str = ""
    priority: str = ""
    reply_type: str = ""
    destination: str = ""
    viewed_date: str = ""
    viewed_user_id: str = ""
    viewed_last_name: str = ""
    archived_date: str = ""
    archived_user_id: str = ""
    archived_last_name: str = ""
    audit_user_id: str = ""
    audit_last_name: str = ""
    transfer_status: str = ""
    transfer_status_date: str = ""
    is_archived: bool = False
    is_restricted: bool = False
    is_copied: bool = False
    status_history: list[StatusHistoryEntry] = field(default_factory=list)
    # Deep-link to the alert in Schwab Advisor Center (si2). Synthesized
    # from the alert id at parse time; not present in the Schwab response.
    sac_url: str = ""
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "AlertDetail":
        attrs = (data.get("attributes") or data)
        common = _parse_alert_attrs(data)
        common["detail_text"] = (attrs.get("detailText") or "")
        common["detail_type"] = (attrs.get("detailType") or "")
        common["status_history"] = [
            StatusHistoryEntry.from_dict(s) for s in (attrs.get("statusHistory") or [])
        ]
        common["viewed_user_id"] = (attrs.get("viewedUserId") or "")
        common["viewed_last_name"] = (attrs.get("viewedLastName") or "")
        common["archived_date"] = (attrs.get("archivedDate") or "")
        common["archived_user_id"] = (attrs.get("archivedUserId") or "")
        common["archived_last_name"] = (attrs.get("archivedLastName") or "")
        common["audit_user_id"] = (attrs.get("auditUserId") or "")
        common["audit_last_name"] = (attrs.get("auditLastName") or "")
        return cls(**common)


@dataclass
class AlertDetailResponse:
    """Response from /alerts/detail/{alert_id}."""

    alert: AlertDetail | None = None
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "AlertDetailResponse":
        d = _unwrap_data(data)
        alert = AlertDetail.from_dict(d) if d else None
        return cls(alert=alert, raw_data=data)


@dataclass
class ArchiveDetail:
    """Detail for a single archived alert."""

    alert_id: int = 0
    has_status_changed: bool = False
    no_change_reason: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "ArchiveDetail":
        return cls(
            alert_id=_safe_int(data, "alertId"),
            has_status_changed=bool(data.get("hasArchivedStatusChanged") or False),
            no_change_reason=(data.get("noArchivedStatusChangeReason") or ""),
        )


@dataclass
class AlertArchiveResponse:
    """Response from POST /alerts/archive."""

    id: str = ""
    are_all_archived: bool = False
    archive_details: list[ArchiveDetail] = field(default_factory=list)
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "AlertArchiveResponse":
        d = _unwrap_data(data)
        attrs = (d.get("attributes") or d)
        details = [
            ArchiveDetail.from_dict(ad)
            for ad in (attrs.get("archiveDetails") or [])
        ]
        return cls(
            id=(d.get("id") or ""),
            are_all_archived=bool(attrs.get("areAllArchived") or False),
            archive_details=details,
            raw_data=data,
        )


@dataclass
class AlertUpdateResponse:
    """Response from PATCH /alerts/{alert_id}."""

    id: str = ""
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "AlertUpdateResponse":
        d = _unwrap_data(data)
        return cls(id=(d.get("id") or ""), raw_data=data)


# --- Service Requests ---


@dataclass
class SubTopic:
    """A sub-topic within a service request topic."""

    name: str = ""
    is_attachment_allowed: bool = False
    is_attachment_required: bool = False
    max_attachment_size: int = 0

    @classmethod
    def from_dict(cls, data: dict) -> "SubTopic":
        return cls(
            name=(data.get("name") or ""),
            is_attachment_allowed=bool(data.get("isAttachmentAllowed") or False),
            is_attachment_required=bool(data.get("isAttachmentRequired") or False),
            max_attachment_size=_safe_int(data, "maxAttachmentSize"),
        )


@dataclass
class ServiceRequestTopic:
    """A service request topic from GET /service-requests."""

    id: str = ""
    name: str = ""
    order: int = 0
    sub_topics: list[SubTopic] = field(default_factory=list)
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "ServiceRequestTopic":
        attrs = (data.get("attributes") or data)
        subs = [SubTopic.from_dict(s) for s in (attrs.get("subTopics") or [])]
        return cls(
            id=(data.get("id") or ""),
            name=(attrs.get("name") or ""),
            order=_safe_int(attrs, "order"),
            sub_topics=subs,
            raw_data=data,
        )


@dataclass
class ServiceRequestTopicsResponse:
    """Response from GET /service-requests (returns available topics)."""

    topics: list[ServiceRequestTopic]

    @classmethod
    def from_dict(cls, data: dict) -> "ServiceRequestTopicsResponse":
        topics = [ServiceRequestTopic.from_dict(t) for t in _data_list(data)]
        return cls(topics=topics)


@dataclass
class ServiceRequestCreateResponse:
    """Response from POST /service-requests."""

    id: str = ""
    formatted_master_account: str = ""
    master_account_name: str = ""
    topic_name: str = ""
    sub_topic_name: str = ""
    description: str = ""
    created_date: str = ""
    creator: str = ""
    status_id: str = ""
    has_attachments: bool = False
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "ServiceRequestCreateResponse":
        d = _unwrap_data(data)
        attrs = (d.get("attributes") or d)
        return cls(
            id=(d.get("id") or ""),
            formatted_master_account=(attrs.get("formattedMasterAccount") or ""),
            master_account_name=(attrs.get("masterAccountName") or ""),
            topic_name=(attrs.get("topicName") or ""),
            sub_topic_name=(attrs.get("subTopicName") or ""),
            description=(attrs.get("description") or ""),
            created_date=(attrs.get("createdDate") or ""),
            creator=(attrs.get("creator") or ""),
            status_id=(attrs.get("statusId") or ""),
            has_attachments=bool(attrs.get("hasAttachments") or False),
            raw_data=data,
        )


# --- Status Feed / Events ---


@dataclass
class StatusEvent:
    """Status event within a status object."""

    id: str = ""
    status_object_id: str = ""
    status: str = ""
    current_status: str = ""
    current_status_detail: str = ""
    created_date: str = ""
    last_updated_date: str = ""
    assignment_group: str = ""
    source: str = ""
    source_id: str = ""
    source_user: str = ""
    can_be_deleted: bool = False
    estimated_completion_date: str = ""
    status_event_info: list[dict] = field(default_factory=list)
    ups_tracking_info: list[dict] = field(default_factory=list)
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "StatusEvent":
        attrs = (data.get("attributes") or data)
        return cls(
            id=(data.get("id") or ""),
            status_object_id=(attrs.get("statusObjectId") or ""),
            status=(attrs.get("status") or ""),
            current_status=(attrs.get("currentStatus") or ""),
            current_status_detail=(attrs.get("currentStatusMessageDetail") or ""),
            created_date=(attrs.get("createdDate") or ""),
            last_updated_date=(attrs.get("lastUpdatedDate") or ""),
            assignment_group=(attrs.get("assignmentGroup") or ""),
            source=(attrs.get("source") or ""),
            source_id=(attrs.get("sourceId") or ""),
            source_user=(attrs.get("sourceUser") or ""),
            can_be_deleted=bool(attrs.get("canBeDeleted") or False),
            estimated_completion_date=(attrs.get("estimatedCompletionDate") or ""),
            status_event_info=attrs.get("statusEventInfo") or [],
            ups_tracking_info=attrs.get("upsTrackingInfo") or [],
            raw_data=data,
        )


@dataclass
class StatusEntryChannel:
    """SAC's "Source" column for a status object — channel + tags
    (e.g. {channel: "Advisor DocuSign", tags: ["E-Signature"]})."""

    channel: str = ""
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "StatusEntryChannel":
        return cls(
            channel=(data.get("channel") or ""),
            tags=data.get("tags") or [],
        )


@dataclass
class StatusClientInfo:
    """Advisor / firm profile metadata attached to a status object.

    Distinct from the AS Client Inquiry API's `ClientInfo` (different
    endpoint, different shape, different purpose).
    """

    profile_type: str = ""
    profile_id: str = ""
    formatted_account: str = ""
    aux_profile_id: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "StatusClientInfo":
        return cls(
            profile_type=(data.get("profileType") or ""),
            profile_id=(data.get("profileId") or ""),
            formatted_account=(data.get("formattedAccount") or ""),
            aux_profile_id=(data.get("auxProfileId") or ""),
        )


@dataclass
class StatusConfidentialInfo:
    """One entry in StatusObject.confidential_info — the system that
    flagged the object as confidential and the value it returned."""

    confidential_decision_system: str = ""
    confidential_decision_value: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "StatusConfidentialInfo":
        return cls(
            confidential_decision_system=(data.get("confidentialDecisionSystem") or ""),
            confidential_decision_value=(data.get("confidentialDecisionValue") or ""),
        )


@dataclass
class StatusAdditionalInfo:
    """Additional info entry (used in StatusObject.status_object_info).

    Captures arbitrary upstream-system metadata: an ID, source system,
    URI, type/value/key, description, category, can-be-deleted flag,
    plus a `process_details` array. The type+value semantics vary per
    source system — read with care.
    """

    additional_info_id: str = ""
    additional_info_system: str = ""
    additional_info_uri: str = ""
    additional_info_type: str = ""
    additional_info_value: str = ""
    additional_info_key: str = ""
    additional_info_description: str = ""
    additional_info_category: str = ""
    can_be_deleted: bool = False
    process_details: list[dict] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "StatusAdditionalInfo":
        return cls(
            additional_info_id=(data.get("additionalInfoId") or ""),
            additional_info_system=(data.get("additionalInfoSystem") or ""),
            additional_info_uri=(data.get("additionalInfoUri") or ""),
            additional_info_type=(data.get("additionalInfoType") or ""),
            additional_info_value=(data.get("additionalInfoValue") or ""),
            additional_info_key=(data.get("additionalInfoKey") or ""),
            additional_info_description=(data.get("additionalInfoDescription") or ""),
            additional_info_category=(data.get("additionalInfoCategory") or ""),
            can_be_deleted=bool(data.get("canBeDeleted") or False),
            process_details=data.get("processDetails") or [],
        )


@dataclass
class StatusObject:
    """Status object within a status feed. Nested objects (entry_channel,
    client_info, confidential_info, status_object_info) are now typed."""

    status_object_id: str = ""
    process_id: str = ""
    bundle_id: str = ""
    created_date: str = ""
    last_updated_date: str = ""
    closed_date: str = ""
    source: str = ""
    source_id: str = ""
    source_user: str = ""
    category: str = ""
    sub_category: str = ""
    formatted_master_account: str = ""
    formatted_account: str = ""
    title: str = ""
    description: str = ""
    account_name: str = ""
    account_registration_type: str = ""
    account_registration_details: str = ""
    myq_case_id: str = ""
    service_request_confirmation_id: str = ""
    action_center_envelope_id: str = ""
    contra_account_info: str = ""
    # SAC's "Source" column (e.g. "Advisor DocuSign") lives in .channel.
    entry_channel: StatusEntryChannel | None = None
    # Advisor profile metadata; not the end-client identity.
    client_info: StatusClientInfo | None = None
    confidential_info: list[StatusConfidentialInfo] = field(default_factory=list)
    status_object_info: list[StatusAdditionalInfo] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    is_updatable: bool = False
    is_confidential: bool = False
    status_events: list[StatusEvent] = field(default_factory=list)
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "StatusObject":
        attrs = (data.get("attributes") or data)
        events = [
            StatusEvent.from_dict(e)
            for e in (attrs.get("statusEvents") or [])
        ]
        ec = attrs.get("entryChannel")
        ci = attrs.get("clientInfo")
        return cls(
            status_object_id=data.get("id", (attrs.get("statusObjectId") or "")),
            process_id=(attrs.get("processId") or ""),
            bundle_id=(attrs.get("bundleId") or ""),
            created_date=(attrs.get("createdDate") or ""),
            last_updated_date=(attrs.get("lastUpdatedDate") or ""),
            closed_date=(attrs.get("closedDate") or ""),
            source=(attrs.get("source") or ""),
            source_id=(attrs.get("sourceId") or ""),
            source_user=(attrs.get("sourceUser") or ""),
            category=(attrs.get("category") or ""),
            sub_category=(attrs.get("subCategory") or ""),
            formatted_master_account=(attrs.get("formattedMasterAccount") or ""),
            formatted_account=(attrs.get("formattedAccount") or ""),
            title=(attrs.get("title") or ""),
            description=(attrs.get("description") or ""),
            account_name=(attrs.get("accountName") or ""),
            account_registration_type=(attrs.get("accountRegistrationType") or ""),
            account_registration_details=(attrs.get("accountRegistrationDetails") or ""),
            myq_case_id=(attrs.get("myqCaseId") or ""),
            service_request_confirmation_id=attrs.get(
                "serviceRequestConfirmationId", ""
            ),
            action_center_envelope_id=(attrs.get("actionCenterEnvelopeId") or ""),
            contra_account_info=(attrs.get("contraAccountInfo") or ""),
            entry_channel=StatusEntryChannel.from_dict(ec) if ec else None,
            client_info=StatusClientInfo.from_dict(ci) if ci else None,
            confidential_info=[
                StatusConfidentialInfo.from_dict(c)
                for c in (attrs.get("confidentialInfo") or [])
            ],
            status_object_info=[
                StatusAdditionalInfo.from_dict(x)
                for x in (attrs.get("statusObjectInfo") or [])
            ],
            tags=attrs.get("tags") or [],
            is_updatable=bool(attrs.get("isUpdatable") or False),
            is_confidential=bool(attrs.get("isConfidential") or False),
            status_events=events,
            raw_data=data,
        )


@dataclass
class StatusFeedCreateResponse:
    """Response from POST /status-feed.

    The POST response inlines statusObjects with their events.
    """

    feed_id: str = ""
    status_objects: list[StatusObject] = field(default_factory=list)
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "StatusFeedCreateResponse":
        d = _unwrap_data(data)
        attrs = (d.get("attributes") or d)
        objects = [
            StatusObject.from_dict(o)
            for o in (attrs.get("statusObjects") or [])
        ]
        return cls(
            feed_id=d.get("id", (attrs.get("feedId") or "")),
            status_objects=objects,
            raw_data=data,
        )


@dataclass
class StatusFeedResponse:
    """Response from GET /status-feed/{feed_id}.

    Returns a list of status objects (JSON:API array).
    """

    status_objects: list[StatusObject] = field(default_factory=list)
    next_cursor: str | None = None
    total_count: int | None = None
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "StatusFeedResponse":
        raw = data.get("data")
        if isinstance(raw, list):
            objects = [StatusObject.from_dict(o) for o in raw]
        elif isinstance(raw, dict):
            objects = [StatusObject.from_dict(raw)]
        else:
            objects = []
        next_cursor, count = _parse_meta(data)
        return cls(
            status_objects=objects,
            next_cursor=next_cursor,
            total_count=count,
            raw_data=data,
        )


@dataclass
class StatusEventsResponse:
    """Response from GET /status-feed/{feed_id}/status-objects/{object_id}/status-events."""

    events: list[StatusEvent]
    next_cursor: str | None = None
    total_count: int | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "StatusEventsResponse":
        events = [StatusEvent.from_dict(e) for e in _data_list(data)]
        next_cursor, count = _parse_meta(data)
        return cls(events=events, next_cursor=next_cursor, total_count=count)


@dataclass
class StatusEventsPostResponse:
    """Response from POST /status-events."""

    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "StatusEventsPostResponse":
        return cls(raw_data=data)


# --- Account Inquiry ---


@dataclass
class MasterAccount:
    """Master account from /master-accounts."""

    id: str = ""
    master_account_name: str = ""
    master_account_type: str = ""
    is_fee_payment_authorized: bool = False
    is_iip: bool = False
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "MasterAccount":
        attrs = (data.get("attributes") or data)
        return cls(
            id=(data.get("id") or ""),
            master_account_name=(attrs.get("masterAccountName") or ""),
            master_account_type=(attrs.get("masterAccountType") or ""),
            is_fee_payment_authorized=bool(attrs.get("isFeePaymentAuthorizationEnabled") or False),
            is_iip=bool(attrs.get("isIip") or False),
            raw_data=data,
        )


@dataclass
class MasterAccountsResponse:
    """Response from GET /master-accounts."""

    master_accounts: list[MasterAccount]
    next_cursor: str | None = None
    total_count: int | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "MasterAccountsResponse":
        items = [MasterAccount.from_dict(m) for m in _data_list(data)]
        next_cursor, count = _parse_meta(data)
        return cls(master_accounts=items, next_cursor=next_cursor, total_count=count)


@dataclass
class AccountInfo:
    """Account from /accounts."""

    id: str = ""
    formatted_master_account: str = ""
    registration_type: str = ""
    title1: str = ""
    title2: str = ""
    title3: str = ""
    linked_to_master_date: str = ""
    established_date: str = ""
    first_name: str = ""
    last_name: str = ""
    organization_name: str = ""
    formatted_taxpayer_id: str = ""
    taxpayer_id_type: str = ""
    is_iip: bool = False
    client_ids: list[int] = field(default_factory=list)
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "AccountInfo":
        attrs = (data.get("attributes") or data)
        return cls(
            id=(data.get("id") or ""),
            formatted_master_account=(attrs.get("formattedMasterAccount") or ""),
            registration_type=(attrs.get("accountRegistrationType") or ""),
            title1=(attrs.get("accountTitle1") or ""),
            title2=(attrs.get("accountTitle2") or ""),
            title3=(attrs.get("accountTitle3") or ""),
            linked_to_master_date=(attrs.get("linkedToMasterDate") or ""),
            established_date=(attrs.get("establishedDate") or ""),
            first_name=(attrs.get("firstName") or ""),
            last_name=(attrs.get("lastName") or ""),
            organization_name=(attrs.get("organizationName") or ""),
            formatted_taxpayer_id=(attrs.get("formattedTaxpayerId") or ""),
            taxpayer_id_type=(attrs.get("taxpayerIdType") or ""),
            is_iip=bool(attrs.get("isIip") or False),
            client_ids=(attrs.get("clientIds") or []),
            raw_data=data,
        )


@dataclass
class AccountsResponse:
    """Response from GET /accounts."""

    accounts: list[AccountInfo]
    next_cursor: str | None = None
    total_count: int | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "AccountsResponse":
        items = [AccountInfo.from_dict(a) for a in _data_list(data)]
        next_cursor, count = _parse_meta(data)
        return cls(accounts=items, next_cursor=next_cursor, total_count=count)


# --- Account Roles ---


@dataclass
class Role:
    """A single role assignment on an account (one entry per account holder).

    Includes beneficiary fields (relationship, percentage, fraction, dollar
    amounts), holder identity, contact info, employment, citizenship(s),
    and Alliance enrollment flags.
    """

    account_holder_id: str = ""
    account_holder_type: str = ""
    role: str = ""
    is_primary_contact: bool = False
    # Beneficiary-specific fields (populated when role is a Beneficiary).
    beneficiary_relationship: str = ""
    beneficiary_asset_percentage: str = ""
    beneficiary_asset_fraction: float = 0.0
    beneficiary_asset_lesser_of_dollar_amount: float = 0.0
    beneficiary_asset_lesser_of_percentage: str = ""
    # Holder identity
    title: str = ""
    first_name: str = ""
    middle_name: str = ""
    last_name: str = ""
    suffix: str = ""
    nick_name: str = ""
    organization_name: str = ""
    formatted_date_of_birth: str = ""
    formatted_taxpayer_id: str = ""
    taxpayer_id_type: str = ""
    # Contact info
    email_address: str = ""
    home_phone: str = ""
    mobile_phone: str = ""
    business_phone: str = ""
    # Employment
    employment_status: str = ""
    employer_name: str = ""
    # Citizenship
    citizenship1: str = ""
    citizenship2: str = ""
    # Schwab Alliance enrollment
    is_account_web_enabled: bool = False
    is_login_id_enrolled: bool = False
    login_id_enroll_status: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "Role":
        return cls(
            account_holder_id=(data.get("accountHolderId") or ""),
            account_holder_type=(data.get("accountHolderType") or ""),
            role=(data.get("role") or ""),
            is_primary_contact=bool(data.get("isPrimaryContact") or False),
            beneficiary_relationship=(data.get("beneficiaryRelationship") or ""),
            beneficiary_asset_percentage=(data.get("beneficiaryAssetPercentage") or ""),
            beneficiary_asset_fraction=_safe_float(data, "beneficiaryAssetFraction") or 0.0,
            beneficiary_asset_lesser_of_dollar_amount=data.get(
                "beneficiaryAssetLesserOfDollarAmount", 0.0
            ) or 0.0,
            beneficiary_asset_lesser_of_percentage=data.get(
                "beneficiaryAssetLesserOfPercentage", ""
            ),
            title=(data.get("title") or ""),
            first_name=(data.get("firstName") or ""),
            middle_name=(data.get("middleName") or ""),
            last_name=(data.get("lastName") or ""),
            suffix=(data.get("suffix") or ""),
            nick_name=(data.get("nickName") or ""),
            organization_name=(data.get("organizationName") or ""),
            formatted_date_of_birth=(data.get("formattedDateOfBirth") or ""),
            formatted_taxpayer_id=(data.get("formattedTaxpayerId") or ""),
            taxpayer_id_type=(data.get("taxpayerIdType") or ""),
            email_address=(data.get("emailAddress") or ""),
            home_phone=(data.get("homePhone") or ""),
            mobile_phone=(data.get("mobilePhone") or ""),
            business_phone=(data.get("businessPhone") or ""),
            employment_status=(data.get("employmentStatus") or ""),
            employer_name=(data.get("employerName") or ""),
            citizenship1=(data.get("citizenship1") or ""),
            citizenship2=(data.get("citizenship2") or ""),
            is_account_web_enabled=bool(data.get("isAccountWebEnabled") or False),
            is_login_id_enrolled=bool(data.get("isLoginIdEnrolled") or False),
            login_id_enroll_status=(data.get("loginIdEnrollStatus") or ""),
        )


@dataclass
class AccountRole:
    """Account role entry from /account-roles. Each account has one or
    more `Role` entries (one per account holder + their role)."""

    id: str = ""
    formatted_account: str = ""
    formatted_master_account: str = ""
    roles: list[Role] = field(default_factory=list)
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "AccountRole":
        attrs = (data.get("attributes") or data)
        return cls(
            id=(data.get("id") or ""),
            formatted_account=(attrs.get("formattedAccount") or ""),
            formatted_master_account=(attrs.get("formattedMasterAccount") or ""),
            roles=[Role.from_dict(r) for r in (attrs.get("roles") or [])],
            raw_data=data,
        )


@dataclass
class AccountRolesResponse:
    """Response from GET /account-roles."""

    account_roles: list[AccountRole]
    next_cursor: str | None = None
    total_count: int | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "AccountRolesResponse":
        items = [AccountRole.from_dict(r) for r in _data_list(data)]
        next_cursor, count = _parse_meta(data)
        return cls(account_roles=items, next_cursor=next_cursor, total_count=count)


# --- Account RMD ---


@dataclass
class AccountRmd:
    """Account RMD data from /account-rmd. Parses the full 42-field
    OpenAPI schema (RMD calculation, contributions, distributions,
    tax withholding elections)."""

    id: str = ""
    formatted_account: str = ""
    formatted_master_account: str = ""
    master_account_type: str = ""
    registration_type: str = ""
    is_roth_ira: bool = False
    opened_this_year: bool = False
    title1: str = ""
    title2: str = ""
    title3: str = ""
    first_name: str = ""
    middle_name: str = ""
    last_name: str = ""
    date_reaches_fifty_nine_and_half: str = ""
    rmd_required_beginning_date: str = ""
    rmd_due_date: str = ""
    current_year: int = 0
    prior_year: int = 0
    rmd_calculation_method: str = ""
    life_expectancy_factor: float = 0.0
    prior_year_end_value: float = 0.0
    # RMD amounts at multiple cadences
    rmd_current_year: float = 0.0
    rmd_current_quarter: float = 0.0
    rmd_current_month: float = 0.0
    rmd_prior_year: float = 0.0
    rmd_two_years_prior: float = 0.0
    # Distribution tracking
    year_to_date_rmd_distributions: float = 0.0
    prior_year_rmd_distributions: float = 0.0
    rmd_distributions_remaining_current_year: float = 0.0
    rmd_distributions_remaining_prior_year: float = 0.0
    total_distributions_year_to_date: float = 0.0
    total_distributions_prior_year: float = 0.0
    total_minus_roth_conv_year_to_date: float = 0.0
    # Contribution tracking
    year_to_date_contribution: float = 0.0
    prior_year_contributions: float = 0.0
    rollover_contribution_this_year: float = 0.0
    roth_conversions_year_to_date: float = 0.0
    # Tax withholding
    is_tax_withholding_elected: bool = False
    is_tax_withholding_federal_opted_out: bool = False
    tax_withholding_election_federal: float = 0.0
    is_tax_withholding_state_opted_out: bool = False
    tax_withholding_election_state: float = 0.0
    tax_withholding_state_code: str = ""
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "AccountRmd":
        attrs = (data.get("attributes") or data)
        return cls(
            id=(data.get("id") or ""),
            formatted_account=(attrs.get("formattedAccount") or ""),
            formatted_master_account=(attrs.get("formattedMasterAccount") or ""),
            master_account_type=(attrs.get("masterAccountType") or ""),
            registration_type=(attrs.get("accountRegistrationType") or ""),
            is_roth_ira=bool(attrs.get("isRothIra") or False),
            opened_this_year=bool(attrs.get("openedThisYear") or False),
            title1=(attrs.get("accountTitle1") or ""),
            title2=(attrs.get("accountTitle2") or ""),
            title3=(attrs.get("accountTitle3") or ""),
            first_name=(attrs.get("firstName") or ""),
            middle_name=(attrs.get("middleName") or ""),
            last_name=(attrs.get("lastName") or ""),
            date_reaches_fifty_nine_and_half=attrs.get(
                "dateReachesFiftyNineAndHalf", ""
            ),
            rmd_required_beginning_date=(attrs.get("rmdRequiredBeginningDate") or ""),
            rmd_due_date=(attrs.get("rmdDueDate") or ""),
            current_year=_safe_int(attrs, "currentYear"),
            prior_year=_safe_int(attrs, "priorYear"),
            rmd_calculation_method=(attrs.get("rmdCalculationMethod") or ""),
            life_expectancy_factor=_safe_float(attrs, "lifeExpectancyFactor"),
            prior_year_end_value=_safe_float(attrs, "priorYearEndValue"),
            rmd_current_year=_safe_float(attrs, "rmdCurrentYear"),
            rmd_current_quarter=_safe_float(attrs, "rmdCurrentQuarter"),
            rmd_current_month=_safe_float(attrs, "rmdCurrentMonth"),
            rmd_prior_year=_safe_float(attrs, "rmdPriorYear"),
            rmd_two_years_prior=_safe_float(attrs, "rmdTwoYearsPrior"),
            year_to_date_rmd_distributions=_safe_float(
                attrs, "yearToDateRmdDistributions"
            ),
            prior_year_rmd_distributions=_safe_float(
                attrs, "priorYearRmdDistributions"
            ),
            rmd_distributions_remaining_current_year=_safe_float(
                attrs, "rmdDistributionsRemainingCurrentYear"
            ),
            rmd_distributions_remaining_prior_year=_safe_float(
                attrs, "rmdDistributionsRemainingPriorYear"
            ),
            total_distributions_year_to_date=_safe_float(
                attrs, "totalDistributionsYearToDate"
            ),
            total_distributions_prior_year=_safe_float(
                attrs, "totalDistributionsPriorYear"
            ),
            total_minus_roth_conv_year_to_date=_safe_float(
                attrs, "totalMinusRothConvYearToDate"
            ),
            year_to_date_contribution=_safe_float(attrs, "yearToDateContribution"),
            prior_year_contributions=_safe_float(attrs, "priorYearContributions"),
            rollover_contribution_this_year=_safe_float(
                attrs, "rolloverContributionThisYear"
            ),
            roth_conversions_year_to_date=_safe_float(
                attrs, "rothConversionsYearToDate"
            ),
            is_tax_withholding_elected=bool(attrs.get("isTaxWithholdingElected") or False),
            is_tax_withholding_federal_opted_out=attrs.get(
                "isTaxWithholdingFederalOptedOut", False
            ),
            tax_withholding_election_federal=_safe_float(
                attrs, "taxWithholdingElectionFederal"
            ),
            is_tax_withholding_state_opted_out=attrs.get(
                "isTaxWithholdingStateOptedOut", False
            ),
            tax_withholding_election_state=_safe_float(
                attrs, "taxWithholdingElectionState"
            ),
            tax_withholding_state_code=(attrs.get("taxWithholdingStateCode") or ""),
            raw_data=data,
        )


@dataclass
class AccountRmdResponse:
    """Response from GET /account-rmd."""

    rmds: list[AccountRmd]
    next_cursor: str | None = None
    total_count: int | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "AccountRmdResponse":
        items = [AccountRmd.from_dict(r) for r in _data_list(data)]
        next_cursor, count = _parse_meta(data)
        return cls(rmds=items, next_cursor=next_cursor, total_count=count)


# --- Account Synchronization ---


@dataclass
class AccountSyncRecord:
    """Account sync record from /account-sync."""

    id: str = ""
    formatted_account: str = ""
    formatted_master_account: str = ""
    registration_type: str = ""
    title1: str = ""
    linked_to_master_date: str = ""
    established_date: str = ""
    client_id: int = 0
    first_name: str = ""
    last_name: str = ""
    organization_name: str = ""
    formatted_date_of_birth: str = ""
    zip_code: str = ""
    formatted_taxpayer_id: str = ""
    taxpayer_id_type: str = ""
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "AccountSyncRecord":
        attrs = (data.get("attributes") or data)
        return cls(
            id=(data.get("id") or ""),
            formatted_account=(attrs.get("formattedAccount") or ""),
            formatted_master_account=(attrs.get("formattedMasterAccount") or ""),
            registration_type=(attrs.get("accountRegistrationType") or ""),
            title1=(attrs.get("accountTitle1") or ""),
            linked_to_master_date=(attrs.get("linkedToMasterDate") or ""),
            established_date=(attrs.get("establishedDate") or ""),
            client_id=_safe_int(attrs, "clientId"),
            first_name=(attrs.get("firstName") or ""),
            last_name=(attrs.get("lastName") or ""),
            organization_name=(attrs.get("organizationName") or ""),
            formatted_date_of_birth=(attrs.get("formattedDateOfBirth") or ""),
            zip_code=(attrs.get("zipCode") or ""),
            formatted_taxpayer_id=(attrs.get("formattedTaxpayerId") or ""),
            taxpayer_id_type=(attrs.get("taxpayerIdType") or ""),
            raw_data=data,
        )


@dataclass
class AccountSyncResponse:
    """Response from GET /account-sync."""

    records: list[AccountSyncRecord]
    next_cursor: str | None = None
    total_count: int | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "AccountSyncResponse":
        items = [AccountSyncRecord.from_dict(r) for r in _data_list(data)]
        next_cursor, count = _parse_meta(data)
        return cls(records=items, next_cursor=next_cursor, total_count=count)


# --- Balances ---


@dataclass
class BalanceDetail:
    """Balance detail from GET /balances/detail.

    Full BalancesDetailGetResponseDataAttributes coverage (52 fields):
    account totals, cash/sweep, per-bucket long/short market values
    (cash vs margin), margin mechanics (buying power, SMA fed call,
    equity), asset-class rollups (treasuries, munis, corporates), and
    the PAA (pledged asset) block.
    """

    id: str = ""
    formatted_account: str = ""
    total_account_value: float = 0.0
    total_market_value: float = 0.0
    total_account_balance: float = 0.0
    total_available_to_withdraw: float = 0.0
    account_net_worth: float = 0.0
    cash: float = 0.0
    cash_and_cash_investments: float = 0.0
    cash_available_to_trade: float = 0.0
    bank_sweep_name: str = ""
    bank_sweep: float = 0.0
    margin_balance: float = 0.0
    short_balance: float = 0.0
    money_market_fund: float = 0.0
    money_market_fund_name: str = ""
    settled_funds: float = 0.0
    securities_market_value_long: float = 0.0
    securities_market_value_short: float = 0.0
    long_securities_market_value_non_marginable: float = 0.0
    securities_market_value_long_non_margin: float = 0.0
    securities_market_value_long_margin: float = 0.0
    securities_market_value_short_non_margin: float = 0.0
    securities_market_value_short_margin: float = 0.0
    options_market_value_long_non_margin: float = 0.0
    options_market_value_long_margin: float = 0.0
    options_market_value_short_non_margin: float = 0.0
    options_market_value_short_margin: float = 0.0
    is_margin_enabled: bool = False
    money_due: float = 0.0
    equities: float = 0.0
    equity_percent: float = 0.0
    equities_including_market_option_value: float = 0.0
    margin_buying_power: float = 0.0
    non_marginable_securities: float = 0.0
    non_marginable_mutual_funds: float = 0.0
    penny_stocks: float = 0.0
    treasuries: float = 0.0
    government_agencies: float = 0.0
    municipal_bonds: float = 0.0
    non_convertible_corporate: float = 0.0
    convertible_corporate: float = 0.0
    options_market_value_long: float = 0.0
    short_options: float = 0.0
    day_trade_buying_power: float = 0.0
    sma_fed_call: float = 0.0
    margin_interest_month_to_date: float = 0.0
    margin_equity: float = 0.0
    option_requirement: float = 0.0
    month_end_dividend_interest_payout: float = 0.0
    paa_eligible_market_value: float = 0.0
    paa_excess_deficiency: float = 0.0
    paa_setup_amount: float = 0.0
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "BalanceDetail":
        attrs = (data.get("attributes") or data)
        return cls(
            id=(data.get("id") or ""),
            formatted_account=(attrs.get("formattedAccount") or ""),
            total_account_value=_safe_float(attrs, "totalAccountValue"),
            total_market_value=_safe_float(attrs, "totalMarketValue"),
            total_account_balance=_safe_float(attrs, "totalAccountBalance"),
            total_available_to_withdraw=_safe_float(attrs, "totalAvailableToWithdraw"),
            account_net_worth=_safe_float(attrs, "accountNetWorth"),
            cash=_safe_float(attrs, "cash"),
            cash_and_cash_investments=_safe_float(attrs, "cashAndCashInvestments"),
            cash_available_to_trade=_safe_float(attrs, "cashAvailableToTrade"),
            bank_sweep_name=(attrs.get("bankSweepName") or ""),
            bank_sweep=_safe_float(attrs, "bankSweep"),
            margin_balance=_safe_float(attrs, "marginBalance"),
            short_balance=_safe_float(attrs, "shortBalance"),
            money_market_fund=_safe_float(attrs, "moneyMarketFund"),
            money_market_fund_name=(attrs.get("moneyMarketFundName") or ""),
            settled_funds=_safe_float(attrs, "settledFunds"),
            securities_market_value_long=_safe_float(attrs, "securitiesMarketValueLong"),
            securities_market_value_short=_safe_float(attrs, "securitiesMarketValueShort"),
            long_securities_market_value_non_marginable=_safe_float(
                attrs, "longSecuritiesMarketValueNonMarginable"),
            securities_market_value_long_non_margin=_safe_float(
                attrs, "securitiesMarketValueLongNonMargin"),
            securities_market_value_long_margin=_safe_float(
                attrs, "securitiesMarketValueLongMargin"),
            securities_market_value_short_non_margin=_safe_float(
                attrs, "securitiesMarketValueShortNonMargin"),
            securities_market_value_short_margin=_safe_float(
                attrs, "securitiesMarketValueShortMargin"),
            options_market_value_long_non_margin=_safe_float(
                attrs, "optionsMarketValueLongNonMargin"),
            options_market_value_long_margin=_safe_float(
                attrs, "optionsMarketValueLongMargin"),
            options_market_value_short_non_margin=_safe_float(
                attrs, "optionsMarketValueShortNonMargin"),
            options_market_value_short_margin=_safe_float(
                attrs, "optionsMarketValueShortMargin"),
            is_margin_enabled=bool(attrs.get("isMarginEnabled") or False),
            money_due=_safe_float(attrs, "moneyDue"),
            equities=_safe_float(attrs, "equities"),
            equity_percent=_safe_float(attrs, "equityPercent"),
            equities_including_market_option_value=_safe_float(
                attrs, "equitiesIncludingMarketOptionValue"),
            margin_buying_power=_safe_float(attrs, "marginBuyingPower"),
            non_marginable_securities=_safe_float(attrs, "nonMarginableSecurities"),
            non_marginable_mutual_funds=_safe_float(attrs, "nonMarginableMutualFunds"),
            penny_stocks=_safe_float(attrs, "pennyStocks"),
            treasuries=_safe_float(attrs, "treasuries"),
            government_agencies=_safe_float(attrs, "governmentAgencies"),
            municipal_bonds=_safe_float(attrs, "municipalBonds"),
            non_convertible_corporate=_safe_float(attrs, "nonConvertibleCorporate"),
            convertible_corporate=_safe_float(attrs, "convertibleCorporate"),
            options_market_value_long=_safe_float(attrs, "optionsMarketValueLong"),
            short_options=_safe_float(attrs, "shortOptions"),
            day_trade_buying_power=_safe_float(attrs, "dayTradeBuyingPower"),
            sma_fed_call=_safe_float(attrs, "smaFedCall"),
            margin_interest_month_to_date=_safe_float(attrs, "marginInterestMonthToDate"),
            margin_equity=_safe_float(attrs, "marginEquity"),
            option_requirement=_safe_float(attrs, "optionRequirement"),
            month_end_dividend_interest_payout=_safe_float(
                attrs, "monthEndDividendInterestPayout"),
            paa_eligible_market_value=_safe_float(attrs, "paaEligibleMarketValue"),
            paa_excess_deficiency=_safe_float(attrs, "paaExcessDeficiency"),
            paa_setup_amount=_safe_float(attrs, "paaSetupAmount"),
            raw_data=data,
        )


@dataclass
class BalanceDetailResponse:
    """Response from GET /balances/detail."""

    balances: list[BalanceDetail]
    next_cursor: str | None = None
    total_count: int | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "BalanceDetailResponse":
        raw = _data_list(data)
        if isinstance(raw, list):
            items = [BalanceDetail.from_dict(b) for b in raw]
        elif isinstance(raw, dict):
            items = [BalanceDetail.from_dict(raw)]
        else:
            items = []
        next_cursor, count = _parse_meta(data)
        return cls(balances=items, next_cursor=next_cursor, total_count=count)


@dataclass
class Balance:
    """One account's balances inside POST /balances/list.

    A narrower record than BalanceDetail (20 fields vs 52) but carries
    account naming the detail route omits, and splits long/short market
    value by cash vs margin.
    """

    formatted_account: str = ""
    account_name: str = ""
    account_title1: str = ""
    total_account_value: float = 0.0
    total_market_value: float = 0.0
    total_account_balance: float = 0.0
    account_net_worth: float = 0.0
    cash_and_cash_investments: float = 0.0
    cash_available_to_trade: float = 0.0
    bank_sweep_name: str = ""
    bank_sweep: float = 0.0
    short_balance: float = 0.0
    settled_funds: float = 0.0
    securities_market_value_long: float = 0.0
    securities_market_value_short: float = 0.0
    securities_market_value_long_margin: float = 0.0
    securities_market_value_long_cash: float = 0.0
    securities_market_value_short_margin: float = 0.0
    securities_market_value_short_cash: float = 0.0
    is_margin_enabled: bool = False
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "Balance":
        return cls(
            formatted_account=(data.get("formattedAccount") or ""),
            account_name=(data.get("accountName") or ""),
            account_title1=(data.get("accountTitle1") or ""),
            total_account_value=_safe_float(data, "totalAccountValue"),
            total_market_value=_safe_float(data, "totalMarketValue"),
            total_account_balance=_safe_float(data, "totalAccountBalance"),
            account_net_worth=_safe_float(data, "accountNetWorth"),
            cash_and_cash_investments=_safe_float(data, "cashAndCashInvestments"),
            cash_available_to_trade=_safe_float(data, "cashAvailableToTrade"),
            bank_sweep_name=(data.get("bankSweepName") or ""),
            bank_sweep=_safe_float(data, "bankSweep"),
            short_balance=_safe_float(data, "shortBalance"),
            settled_funds=_safe_float(data, "settledFunds"),
            securities_market_value_long=_safe_float(data, "securitiesMarketValueLong"),
            securities_market_value_short=_safe_float(data, "securitiesMarketValueShort"),
            securities_market_value_long_margin=_safe_float(
                data, "securitiesMarketValueLongMargin"),
            securities_market_value_long_cash=_safe_float(
                data, "securitiesMarketValueLongCash"),
            securities_market_value_short_margin=_safe_float(
                data, "securitiesMarketValueShortMargin"),
            securities_market_value_short_cash=_safe_float(
                data, "securitiesMarketValueShortCash"),
            is_margin_enabled=bool(data.get("isMarginEnabled") or False),
            raw_data=data,
        )


@dataclass
class TotalBalances:
    """Cross-account rollup on POST /balances/list (spec: TotalBalance)."""

    total_account_value: float = 0.0
    total_market_value: float = 0.0
    total_cash_and_cash_investments: float = 0.0
    total_short_balance: float = 0.0
    total_settled_funds: float = 0.0
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "TotalBalances":
        return cls(
            total_account_value=_safe_float(data, "totalAccountValue"),
            total_market_value=_safe_float(data, "totalMarketValue"),
            total_cash_and_cash_investments=_safe_float(
                data, "totalCashAndCashInvestments"),
            total_short_balance=_safe_float(data, "totalShortBalance"),
            total_settled_funds=_safe_float(data, "totalSettledFunds"),
            raw_data=data,
        )


@dataclass
class BalanceListResponse:
    """Response from POST /balances/list (single-item wrapper with nested
    balances).

    ``balances`` holds typed Balance records as of v0.3.0 (previously
    raw dicts). ``errors`` carries per-account failures for accounts the
    caller asked about but Schwab could not serve — a partial success is
    a 200, so callers must check it.
    """

    balances: list[Balance] = field(default_factory=list)
    total_balances: TotalBalances | None = None
    as_of_date: str = ""
    errors: list[dict] = field(default_factory=list)
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "BalanceListResponse":
        d = _unwrap_data(data)
        attrs = (d.get("attributes") or d)
        totals = attrs.get("totalBalances")
        errors = attrs.get("errors")
        return cls(
            balances=[
                Balance.from_dict(b)
                for b in (attrs.get("balances") or [])
                if isinstance(b, dict)
            ],
            total_balances=(
                TotalBalances.from_dict(totals) if isinstance(totals, dict) else None
            ),
            as_of_date=(attrs.get("asOfDate") or ""),
            errors=(errors if isinstance(errors, list) else []),
            raw_data=data,
        )


# --- Positions ---


@dataclass
class Position:
    """One holding from GET /positions/detail.

    ``day_change`` is a STRING in the spec (Schwab formats it, e.g.
    "-1.23"), unlike quantity/market_value which are numeric —
    don't assume it parses as a float.
    """

    formatted_account: str = ""
    type: str = ""
    security_name: str = ""
    symbol: str = ""
    security_number: int = 0
    security_type: str = ""
    # SPEC DRIFT: prod returns cusipNumber on every position; the
    # Positions OpenAPI spec does not declare it (verified 2026-07-28).
    cusip_number: str = ""
    quantity: float = 0.0
    quoted_price: float = 0.0
    price_stale_status: str = ""
    price_stale_status_message: str = ""
    market_value: float = 0.0
    day_change: str = ""
    percentageof_account_assets_long: float = 0.0
    are_capital_gains_reinvested: bool = False
    is_capital_gains_reinvest_editable: bool = False
    are_dividends_reinvested: bool = False
    is_dividend_reinvest_editable: bool = False
    item_issue_id: int = 0
    suffix: int = 0
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "Position":
        return cls(
            formatted_account=(data.get("formattedAccount") or ""),
            type=(data.get("type") or ""),
            security_name=(data.get("securityName") or ""),
            symbol=(data.get("symbol") or ""),
            security_number=_safe_int(data, "securityNumber"),
            security_type=(data.get("securityType") or ""),
            cusip_number=(data.get("cusipNumber") or ""),
            quantity=_safe_float(data, "quantity"),
            quoted_price=_safe_float(data, "quotedPrice"),
            price_stale_status=(data.get("priceStaleStatus") or ""),
            price_stale_status_message=(data.get("priceStaleStatusMessage") or ""),
            market_value=_safe_float(data, "marketValue"),
            day_change=str(data.get("dayChange") or ""),
            percentageof_account_assets_long=_safe_float(
                data, "percentageofAccountAssetsLong"),
            are_capital_gains_reinvested=bool(
                data.get("areCapitalGainsReinvested") or False),
            is_capital_gains_reinvest_editable=bool(
                data.get("isCapitalGainsReinvestEditable") or False),
            are_dividends_reinvested=bool(data.get("areDividendsReinvested") or False),
            is_dividend_reinvest_editable=bool(
                data.get("isDividendReinvestEditable") or False),
            item_issue_id=_safe_int(data, "itemIssueId"),
            suffix=_safe_int(data, "suffix"),
            raw_data=data,
        )


@dataclass
class TotalPositions:
    """Account-level rollup accompanying a positions response.

    Serves both /positions/detail (6 fields) and /positions/list
    (TotalListPositions — the same shape minus the day-change pair,
    which simply stays 0.0).
    """

    total_account_value: float = 0.0
    total_short_balance: float = 0.0
    total_cash_and_cash_investments: float = 0.0
    total_market_value: float = 0.0
    total_day_change: float = 0.0
    total_day_change_percentage: float = 0.0
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "TotalPositions":
        return cls(
            total_account_value=_safe_float(data, "totalAccountValue"),
            total_short_balance=_safe_float(data, "totalShortBalance"),
            total_cash_and_cash_investments=_safe_float(
                data, "totalCashAndCashInvestments"),
            total_market_value=_safe_float(data, "totalMarketValue"),
            total_day_change=_safe_float(data, "totalDayChange"),
            total_day_change_percentage=_safe_float(data, "totalDayChangePercentage"),
            raw_data=data,
        )


@dataclass
class ListPosition:
    """One holding from POST /positions/list.

    Narrower than Position (15 fields vs 19) but carries the account
    naming the detail route omits — the multi-account view trades
    per-holding depth for cross-account labelling.
    """

    formatted_account: str = ""
    account_name: str = ""
    account_title1: str = ""
    security_name: str = ""
    symbol: str = ""
    security_type: str = ""
    # SPEC DRIFT: prod returns cusipNumber here too (verified 2026-07-28).
    cusip_number: str = ""
    quantity: float = 0.0
    quoted_price: float = 0.0
    price_stale_status: str = ""
    price_stale_status_message: str = ""
    market_value: float = 0.0
    percentageof_account_assets_long: float = 0.0
    type: str = ""
    are_capital_gains_reinvested: bool = False
    are_dividends_reinvested: bool = False
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "ListPosition":
        return cls(
            formatted_account=(data.get("formattedAccount") or ""),
            account_name=(data.get("accountName") or ""),
            account_title1=(data.get("accountTitle1") or ""),
            security_name=(data.get("securityName") or ""),
            symbol=(data.get("symbol") or ""),
            security_type=(data.get("securityType") or ""),
            cusip_number=(data.get("cusipNumber") or ""),
            quantity=_safe_float(data, "quantity"),
            quoted_price=_safe_float(data, "quotedPrice"),
            price_stale_status=(data.get("priceStaleStatus") or ""),
            price_stale_status_message=(data.get("priceStaleStatusMessage") or ""),
            market_value=_safe_float(data, "marketValue"),
            percentageof_account_assets_long=_safe_float(
                data, "percentageofAccountAssetsLong"),
            type=(data.get("type") or ""),
            are_capital_gains_reinvested=bool(
                data.get("areCapitalGainsReinvested") or False),
            are_dividends_reinvested=bool(data.get("areDividendsReinvested") or False),
            raw_data=data,
        )


@dataclass
class PositionDetailResponse:
    """Response from GET /positions/detail (single-item wrapper).

    ``positions`` holds typed Position records as of v0.3.0
    (previously raw dicts).
    """

    positions: list[Position] = field(default_factory=list)
    total_positions: TotalPositions | None = None
    next_cursor: str | None = None
    total_count: int | None = None
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "PositionDetailResponse":
        d = _unwrap_data(data)
        attrs = (d.get("attributes") or d)
        next_cursor, count = _parse_meta(data)
        totals = attrs.get("totalPositions")
        return cls(
            positions=[
                Position.from_dict(p)
                for p in (attrs.get("positions") or [])
                if isinstance(p, dict)
            ],
            total_positions=(
                TotalPositions.from_dict(totals) if isinstance(totals, dict) else None
            ),
            next_cursor=next_cursor,
            total_count=count,
            raw_data=data,
        )


@dataclass
class PositionListResponse:
    """Response from POST /positions/list.

    ``positions`` holds typed ListPosition records as of v0.3.0
    (previously raw dicts). ``errors`` carries per-account failures —
    a partial success is still a 200, so callers must check it.
    """

    positions: list[ListPosition] = field(default_factory=list)
    total_positions: TotalPositions | None = None
    as_of_date: str = ""
    errors: list[dict] = field(default_factory=list)
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "PositionListResponse":
        d = _unwrap_data(data)
        attrs = (d.get("attributes") or d)
        totals = attrs.get("totalPositions")
        errors = attrs.get("errors")
        return cls(
            positions=[
                ListPosition.from_dict(p)
                for p in (attrs.get("positions") or [])
                if isinstance(p, dict)
            ],
            total_positions=(
                TotalPositions.from_dict(totals) if isinstance(totals, dict) else None
            ),
            as_of_date=(attrs.get("asOfDate") or ""),
            errors=(errors if isinstance(errors, list) else []),
            raw_data=data,
        )


# --- Client Inquiry ---


@dataclass
class ClientInfo:
    """Client info from /client-inquiries."""

    id: int | str = ""
    first_name: str = ""
    last_name: str = ""
    organization_name: str = ""
    city: str = ""
    state: str = ""
    month_year_of_birth: str = ""
    account_name: str = ""
    established_date: str = ""
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "ClientInfo":
        attrs = (data.get("attributes") or data)
        return cls(
            id=(data.get("id") or ""),
            first_name=(attrs.get("firstName") or ""),
            last_name=(attrs.get("lastName") or ""),
            organization_name=(attrs.get("organizationName") or ""),
            city=(attrs.get("city") or ""),
            state=(attrs.get("state") or ""),
            month_year_of_birth=(attrs.get("monthYearOfBirth") or ""),
            account_name=(attrs.get("accountName") or ""),
            established_date=(attrs.get("establishedDate") or ""),
            raw_data=data,
        )


@dataclass
class ClientInquiryResponse:
    """Response from GET /client-inquiries."""

    clients: list[ClientInfo]
    next_cursor: str | None = None
    total_count: int | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "ClientInquiryResponse":
        items = [ClientInfo.from_dict(c) for c in _data_list(data)]
        next_cursor, count = _parse_meta(data)
        return cls(clients=items, next_cursor=next_cursor, total_count=count)


# --- Account Owners ---


@dataclass
class AccountOwnerListResponse:
    """Response from POST /account-owners/list.

    Shares the nested-wrapper shape of ProfilesListResponse: the records
    and an ``errors.invalidAccounts`` list live under
    ``data.attributes``, not as JSON:API resource objects.
    """

    account_owners: list[dict] = field(default_factory=list)
    invalid_accounts: list[str] = field(default_factory=list)
    next_cursor: str | None = None
    total_count: int | None = None
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "AccountOwnerListResponse":
        d = _unwrap_data(data)
        attrs = (d.get("attributes") or d)
        errors = attrs.get("errors") or {}
        next_cursor, count = _parse_meta(data)
        return cls(
            account_owners=(attrs.get("accountOwners") or []),
            invalid_accounts=(errors.get("invalidAccounts") or []),
            next_cursor=next_cursor,
            total_count=count,
            raw_data=data,
        )


# --- Document Preferences ---


@dataclass
class ReportPreferences:
    """How statements / trade confirmations are formatted for the
    account (statement type, bundling, format)."""

    statement_type: str = ""
    is_statement_bundled: bool = False
    trade_confirmations_format: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "ReportPreferences":
        return cls(
            statement_type=(data.get("statementType") or ""),
            is_statement_bundled=bool(data.get("isStatementBundled") or False),
            trade_confirmations_format=(data.get("tradeConfirmationsFormat") or ""),
        )


@dataclass
class CommunicationDetail:
    """One entry in DocumentPreference.issuer_communications."""

    type: str = ""
    original: str = ""
    informational_copy: str = ""
    last_updated_date: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "CommunicationDetail":
        return cls(
            type=(data.get("type") or ""),
            original=(data.get("original") or ""),
            informational_copy=(data.get("informationalCopy") or ""),
            last_updated_date=(data.get("lastUpdatedDate") or ""),
        )


@dataclass
class DeliveryPreferences:
    """Document delivery configuration: paper/e-statement enrollment,
    suppression, equity commission terms, dup statement recipients."""

    enrollment_instruction: str = ""
    is_statement_suppression_enabled: bool = False
    equity_commission_amount: str = ""
    legacy_source: str = ""
    document_delivery_options: list[dict] = field(default_factory=list)
    duplicate_statements: list[dict] = field(default_factory=list)
    duplicate_trade_confirmations: list[dict] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "DeliveryPreferences":
        return cls(
            enrollment_instruction=(data.get("enrollmentInstruction") or ""),
            is_statement_suppression_enabled=data.get(
                "isStatementSuppressionEnabled", False
            ),
            equity_commission_amount=(data.get("equityCommissionAmount") or ""),
            legacy_source=(data.get("legacySource") or ""),
            document_delivery_options=data.get("documentDeliveryOptions") or [],
            duplicate_statements=data.get("duplicateStatements") or [],
            duplicate_trade_confirmations=data.get("duplicateTradeConfirmations") or [],
        )


@dataclass
class ManagedAccountInfo:
    """Managed-account platform info attached to a doc-prefs record
    (only populated when the account is in a managed program)."""

    platform: str = ""
    money_manager: str = ""
    investment_strategy: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "ManagedAccountInfo":
        return cls(
            platform=(data.get("platform") or ""),
            money_manager=(data.get("moneyManager") or ""),
            investment_strategy=(data.get("investmentStrategy") or ""),
        )


@dataclass
class DocumentPreference:
    """Per-account document delivery preferences from
    /document-preferences/list. Composes report prefs + delivery prefs +
    managed-account info + issuer communications."""

    formatted_account: str = ""
    report_preferences: ReportPreferences | None = None
    delivery: DeliveryPreferences | None = None
    managed_account: ManagedAccountInfo | None = None
    issuer_communications: list[CommunicationDetail] = field(default_factory=list)
    # SPEC DRIFT: prod returns isIssuerDisclosureOptedOut on every account;
    # the Document Preferences spec does not declare it (verified
    # 2026-07-28).
    is_issuer_disclosure_opted_out: bool = False
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "DocumentPreference":
        rp = data.get("reportPreferences")
        dl = data.get("delivery")
        ma = data.get("managedAccount")
        ic = data.get("issuerCommunications") or []
        return cls(
            formatted_account=(data.get("formattedAccount") or ""),
            report_preferences=ReportPreferences.from_dict(rp) if rp else None,
            delivery=DeliveryPreferences.from_dict(dl) if dl else None,
            managed_account=ManagedAccountInfo.from_dict(ma) if ma else None,
            issuer_communications=[CommunicationDetail.from_dict(c) for c in ic],
            is_issuer_disclosure_opted_out=bool(
                data.get("isIssuerDisclosureOptedOut") or False),
            raw_data=data,
        )


@dataclass
class DocumentPreferencesResponse:
    """Response from POST /document-preferences/list. Per-account
    entries are now typed (DocumentPreference) instead of raw dicts."""

    document_preferences: list[DocumentPreference] = field(default_factory=list)
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "DocumentPreferencesResponse":
        d = _unwrap_data(data)
        attrs = (d.get("attributes") or d) if isinstance(d, dict) else {}
        items = attrs.get("documentPreferences") or []
        return cls(
            document_preferences=[
                DocumentPreference.from_dict(x) if isinstance(x, dict) else x
                for x in items
            ],
            raw_data=data,
        )


# --- Address Changes ---


@dataclass
class AddressChange:
    """Address change action from /address-changes.

    Response schema from Schwab docs - field names are known even though
    sandbox returns empty data.
    """

    id: str = ""
    action_source: str = ""
    action_status: str = ""
    created_date: str = ""
    submitted_date: str = ""
    delivered_date: str = ""
    completed_date: str = ""
    last_updated_date: str = ""
    original_customer_addresses: list[dict] = field(default_factory=list)
    updated_customer_addresses: list[dict] = field(default_factory=list)
    trust_profiles: list[dict] = field(default_factory=list)
    account_address_links: list[dict] = field(default_factory=list)
    other_account_holders: list[dict] = field(default_factory=list)
    organization_profiles: list[dict] = field(default_factory=list)
    relationships: dict | None = None
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "AddressChange":
        attrs = (data.get("attributes") or data)
        return cls(
            id=(data.get("id") or ""),
            action_source=(attrs.get("actionSource") or ""),
            action_status=(attrs.get("actionStatus") or ""),
            created_date=(attrs.get("createdDate") or ""),
            submitted_date=(attrs.get("submittedDate") or ""),
            delivered_date=(attrs.get("deliveredDate") or ""),
            completed_date=(attrs.get("completedDate") or ""),
            last_updated_date=(attrs.get("lastUpdatedDate") or ""),
            original_customer_addresses=(attrs.get("originalCustomerAddresses") or []),
            updated_customer_addresses=(attrs.get("updatedCustomerAddresses") or []),
            trust_profiles=(attrs.get("trustProfiles") or []),
            account_address_links=(attrs.get("accountAddressLinks") or []),
            other_account_holders=(attrs.get("otherAccountHolders") or []),
            organization_profiles=(attrs.get("organizationProfiles") or []),
            relationships=data.get("relationships"),
            raw_data=data,
        )


@dataclass
class AddressChangesResponse:
    """Response from GET /address-changes.

    Supports JSON:API include=customer sideloading via the included field.
    """

    changes: list[AddressChange]
    included: list[dict] = field(default_factory=list)
    next_cursor: str | None = None
    total_count: int | None = None
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "AddressChangesResponse":
        raw = _data_list(data)
        if isinstance(raw, list):
            changes = [AddressChange.from_dict(c) for c in raw]
        elif raw:
            changes = [AddressChange.from_dict(raw)]
        else:
            changes = []
        next_cursor, count = _parse_meta(data)
        return cls(
            changes=changes,
            included=(data.get("included") or []),
            next_cursor=next_cursor,
            total_count=count,
            raw_data=data,
        )


# --- Profiles List ---


@dataclass
class ProfilesListResponse:
    """Response from POST /profiles/list.

    ``invalid_accounts`` carries the accounts Schwab explicitly rejected
    (masked, e.g. "****3226"). It is NOT a complete record of what went
    missing: some unresolvable accounts are dropped from ``profiles``
    without ever appearing here (verified 2026-07-29). Always diff the
    returned profile count against the accounts requested.
    """

    profiles: list[dict] = field(default_factory=list)
    invalid_accounts: list[str] = field(default_factory=list)
    next_cursor: str | None = None
    total_count: int | None = None
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "ProfilesListResponse":
        d = _unwrap_data(data)
        attrs = (d.get("attributes") or d)
        errors = attrs.get("errors") or {}
        next_cursor, count = _parse_meta(data)
        return cls(
            profiles=(attrs.get("profiles") or []),
            invalid_accounts=(errors.get("invalidAccounts") or []),
            next_cursor=next_cursor,
            total_count=count,
            raw_data=data,
        )


# --- Cost Basis ---


@dataclass
class CostBasisAccountPreference:
    """Individual account cost basis preference."""

    formatted_account: str = ""
    account_title: str = ""
    is_non_taxable_account: bool = False
    initial_cost_basis_source: str = ""
    accounting_method: str = ""
    average_mutual_funds: bool = False
    adjust_cost_basis_for_fixed_income: bool = False
    on_gain_loss_tab: bool = False
    has_schwab_alliance_log_on: bool = False
    cost_basis_on_statements: str = ""
    year_end_gain_loss_report: str = ""
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "CostBasisAccountPreference":
        return cls(
            formatted_account=(data.get("formattedAccount") or ""),
            account_title=(data.get("accountTitle") or ""),
            is_non_taxable_account=bool(data.get("isNonTaxableAccount") or False),
            initial_cost_basis_source=(data.get("initialCostBasisSource") or ""),
            accounting_method=(data.get("accountingMethod") or ""),
            average_mutual_funds=bool(data.get("averageMutualFunds") or False),
            adjust_cost_basis_for_fixed_income=bool(data.get("adjustCostBasisForFixedIncome") or False),
            on_gain_loss_tab=bool(data.get("onGainLossTab") or False),
            has_schwab_alliance_log_on=bool(data.get("hasSchwabAllianceLogOn") or False),
            cost_basis_on_statements=(data.get("costBasisOnStatements") or ""),
            year_end_gain_loss_report=(data.get("yearEndGainLossReport") or ""),
            raw_data=data,
        )


@dataclass
class CostBasisPreferencesResponse:
    """Response from GET /cost-basis/account-preferences."""

    summary: dict = field(default_factory=dict)
    details: list[CostBasisAccountPreference] = field(default_factory=list)
    next_cursor: str | None = None
    total_count: int | None = None
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "CostBasisPreferencesResponse":
        d = _unwrap_data(data)
        attrs = (d.get("attributes") or d)
        details = [
            CostBasisAccountPreference.from_dict(det)
            for det in (attrs.get("details") or [])
        ]
        next_cursor, count = _parse_meta(data)
        return cls(
            summary=(attrs.get("summary") or {}),
            details=details,
            next_cursor=next_cursor,
            total_count=count,
            raw_data=data,
        )


@dataclass
class RglTransactionLot:
    """One tax lot inside an RGL transaction.

    Every numeric is a FORMATTED STRING, as everywhere in Cost Basis
    ("($349.02)" for negatives, "25.87%", "Missing", "N/A") — never
    coerce these to float without parsing the formatting first.
    ``notes`` is an open-ended `Notes` schema (no declared properties),
    so it passes through as whatever Schwab sends.
    """

    lot_id: str = ""
    lot_type: str = ""
    realized_gain_loss_dollar: str = ""
    realized_gain_loss_percent: str = ""
    short_term_realized_gain_loss: str = ""
    long_term_realized_gain_loss: str = ""
    quantity: str = ""
    proceeds: str = ""
    proceeds_per_share: str = ""
    cost_basis: str = ""
    cost_per_share: str = ""
    disallowed_loss: str = ""
    adjusted_realized_gain_loss_dollar: str = ""
    adjusted_realized_gain_loss_percent: str = ""
    adjusted_cost_basis: str = ""
    adjusted_cost_per_share: str = ""
    adjusted_disallowed_loss: str = ""
    acquired_or_opened_date: str = ""
    sold_or_closed_date: str = ""
    holding_period: str = ""
    notes: str | list | dict = ""
    # SPEC DRIFT: prod returns eventId on lots (verified 2026-07-28).
    event_id: str = ""
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "RglTransactionLot":
        return cls(
            lot_id=(data.get("lotId") or ""),
            lot_type=(data.get("lotType") or ""),
            realized_gain_loss_dollar=(data.get("realizedGainLossDollar") or ""),
            realized_gain_loss_percent=(data.get("realizedGainLossPercent") or ""),
            short_term_realized_gain_loss=(data.get("shortTermRealizedGainLoss") or ""),
            long_term_realized_gain_loss=(data.get("longTermRealizedGainLoss") or ""),
            quantity=(data.get("quantity") or ""),
            proceeds=(data.get("proceeds") or ""),
            proceeds_per_share=(data.get("proceedsPerShare") or ""),
            cost_basis=(data.get("costBasis") or ""),
            cost_per_share=(data.get("costPerShare") or ""),
            disallowed_loss=(data.get("disallowedLoss") or ""),
            adjusted_realized_gain_loss_dollar=(
                data.get("adjustedRealizedGainLossDollar") or ""),
            adjusted_realized_gain_loss_percent=(
                data.get("adjustedRealizedGainLossPercent") or ""),
            adjusted_cost_basis=(data.get("adjustedCostBasis") or ""),
            adjusted_cost_per_share=(data.get("adjustedCostPerShare") or ""),
            adjusted_disallowed_loss=(data.get("adjustedDisallowedLoss") or ""),
            acquired_or_opened_date=(data.get("acquiredOrOpenedDate") or ""),
            sold_or_closed_date=(data.get("soldOrClosedDate") or ""),
            holding_period=(data.get("holdingPeriod") or ""),
            notes=(data.get("notes") or ""),
            event_id=str(data.get("eventId") or ""),
            raw_data=data,
        )


@dataclass
class RglSummary:
    """Account-level realized gain/loss rollup (formatted strings)."""

    formatted_account: str = ""
    total_known_realized_gain_loss_dollar: str = ""
    total_known_realized_gain_loss_percent: str = ""
    total_known_short_term_realized_gain_loss: str = ""
    total_known_long_term_realized_gain_loss: str = ""
    total_known_proceeds: str = ""
    total_known_cost_basis: str = ""
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "RglSummary":
        return cls(
            formatted_account=(data.get("formattedAccount") or ""),
            total_known_realized_gain_loss_dollar=(
                data.get("totalKnownRealizedGainLossDollar") or ""),
            total_known_realized_gain_loss_percent=(
                data.get("totalKnownRealizedGainLossPercent") or ""),
            total_known_short_term_realized_gain_loss=(
                data.get("totalKnownShortTermRealizedGainLoss") or ""),
            total_known_long_term_realized_gain_loss=(
                data.get("totalKnownLongTermRealizedGainLoss") or ""),
            total_known_proceeds=(data.get("totalKnownProceeds") or ""),
            total_known_cost_basis=(data.get("totalKnownCostBasis") or ""),
            raw_data=data,
        )


@dataclass
class UglSummary:
    """Account-level unrealized gain/loss rollup (formatted strings)."""

    formatted_account: str = ""
    total_known_unrealized_gain_loss_dollar: str = ""
    total_known_unrealized_gain_loss_percent: str = ""
    total_known_cost_basis: str = ""
    total_known_market_value: str = ""
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "UglSummary":
        return cls(
            formatted_account=(data.get("formattedAccount") or ""),
            total_known_unrealized_gain_loss_dollar=(
                data.get("totalKnownUnrealizedGainLossDollar") or ""),
            total_known_unrealized_gain_loss_percent=(
                data.get("totalKnownUnrealizedGainLossPercent") or ""),
            total_known_cost_basis=(data.get("totalKnownCostBasis") or ""),
            total_known_market_value=(data.get("totalKnownMarketValue") or ""),
            raw_data=data,
        )


@dataclass
class RglTransaction:
    """Realized gain/loss transaction from /cost-basis/rgl-transactions.

    Note: dollar/percent values are formatted strings (e.g. "($349.02)", "25.87%"),
    not floats. Negative values use parentheses.
    """

    transaction_id: str = ""
    symbol: str = ""
    security_name: str = ""
    total_realized_gain_loss_dollar: str = ""
    total_realized_gain_loss_percent: str = ""
    short_term_realized_gain_loss: str = ""
    long_term_realized_gain_loss: str = ""
    quantity: str = ""
    total_proceeds: str = ""
    cost_basis: str = ""
    acquired_or_opened_date: str = ""
    sold_or_closed_date: str = ""
    notes: str = ""
    transaction_lots: list[RglTransactionLot] = field(default_factory=list)
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "RglTransaction":
        return cls(
            transaction_id=(data.get("transactionId") or ""),
            symbol=(data.get("symbol") or ""),
            security_name=(data.get("securityName") or ""),
            total_realized_gain_loss_dollar=(data.get("totalRealizedGainLossDollar") or ""),
            total_realized_gain_loss_percent=(data.get("totalRealizedGainLossPercent") or ""),
            short_term_realized_gain_loss=(data.get("shortTermRealizedGainLoss") or ""),
            long_term_realized_gain_loss=(data.get("longTermRealizedGainLoss") or ""),
            quantity=(data.get("quantity") or ""),
            total_proceeds=(data.get("totalProceeds") or ""),
            cost_basis=(data.get("costBasis") or ""),
            acquired_or_opened_date=(data.get("acquiredOrOpenedDate") or ""),
            sold_or_closed_date=(data.get("soldOrClosedDate") or ""),
            notes=(data.get("notes") or ""),
            transaction_lots=[
                RglTransactionLot.from_dict(lot)
                for lot in (data.get("transactionLots") or [])
                if isinstance(lot, dict)
            ],
            raw_data=data,
        )


@dataclass
class CostBasisRglResponse:
    """Response from GET /cost-basis/rgl-transactions.

    ``summary`` is a typed RglSummary as of v0.3.0 (previously a raw
    dict); the untyped payload is still on ``raw_data``.
    """

    summary: RglSummary | None = None
    transactions: list[RglTransaction] = field(default_factory=list)
    next_cursor: str | None = None
    total_count: int | None = None
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "CostBasisRglResponse":
        d = _unwrap_data(data)
        attrs = (d.get("attributes") or d)
        txns = [RglTransaction.from_dict(t) for t in (attrs.get("transactions") or [])]
        next_cursor, count = _parse_meta(data)
        summary = attrs.get("summary")
        return cls(
            summary=(
                RglSummary.from_dict(summary) if isinstance(summary, dict) else None
            ),
            transactions=txns,
            next_cursor=next_cursor,
            total_count=count,
            raw_data=data,
        )


@dataclass
class UglPosition:
    """Unrealized gain/loss position from /cost-basis/ugl-positions.

    Note: dollar/percent values are formatted strings (e.g. "$257,525.32",
    "194.31%", "Missing"). Not floats.
    """

    position_id: str = ""
    symbol: str = ""
    security_name: str = ""
    unrealized_gain_loss_dollar: str = ""
    unrealized_gain_loss_percent: str = ""
    quantity: str = ""
    cost_basis: str = ""
    market_value: str = ""
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "UglPosition":
        return cls(
            position_id=(data.get("positionId") or ""),
            symbol=(data.get("symbol") or ""),
            security_name=(data.get("securityName") or ""),
            unrealized_gain_loss_dollar=(data.get("unrealizedGainLossDollar") or ""),
            unrealized_gain_loss_percent=(data.get("unrealizedGainLossPercent") or ""),
            quantity=(data.get("quantity") or ""),
            cost_basis=(data.get("costBasis") or ""),
            market_value=(data.get("marketValue") or ""),
            raw_data=data,
        )


@dataclass
class UglPositionLot:
    """One tax lot of an unrealized-gain/loss position.

    Values are FORMATTED STRINGS throughout ("$257,525.32", "194.31%",
    "Missing", "N/A") — the lot-level record a client associate needs
    for wash-sale and holding-period questions. ``notes`` is an
    open-ended `Notes` schema and passes through as sent.
    """

    lot_id: str = ""
    lot_type: str = ""
    unrealized_gain_loss_dollar: str = ""
    unrealized_gain_loss_percent: str = ""
    quantity: str = ""
    cost_basis: str = ""
    cost_per_share: str = ""
    current_price: str = ""
    todays_change_in_price_dollar: str = ""
    todays_change_in_price_percent: str = ""
    market_value: str = ""
    todays_change_in_value_dollar: str = ""
    todays_change_in_value_percent: str = ""
    adjusted_unrealized_gain_loss_dollar: str = ""
    adjusted_unrealized_gain_loss_percent: str = ""
    adjusted_cost_basis: str = ""
    adjusted_cost_per_share: str = ""
    acquired_or_opened_date: str = ""
    holding_period: str = ""
    notes: str | list | dict = ""
    # SPEC DRIFT: prod returns eventId on lots (verified 2026-07-28).
    event_id: str = ""
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "UglPositionLot":
        return cls(
            lot_id=(data.get("lotId") or ""),
            lot_type=(data.get("lotType") or ""),
            unrealized_gain_loss_dollar=(data.get("unrealizedGainLossDollar") or ""),
            unrealized_gain_loss_percent=(data.get("unrealizedGainLossPercent") or ""),
            quantity=(data.get("quantity") or ""),
            cost_basis=(data.get("costBasis") or ""),
            cost_per_share=(data.get("costPerShare") or ""),
            current_price=(data.get("currentPrice") or ""),
            todays_change_in_price_dollar=(data.get("todaysChangeInPriceDollar") or ""),
            todays_change_in_price_percent=(
                data.get("todaysChangeInPricePercent") or ""),
            market_value=(data.get("marketValue") or ""),
            todays_change_in_value_dollar=(data.get("todaysChangeInValueDollar") or ""),
            todays_change_in_value_percent=(
                data.get("todaysChangeInValuePercent") or ""),
            adjusted_unrealized_gain_loss_dollar=(
                data.get("adjustedUnrealizedGainLossDollar") or ""),
            adjusted_unrealized_gain_loss_percent=(
                data.get("adjustedUnrealizedGainLossPercent") or ""),
            adjusted_cost_basis=(data.get("adjustedCostBasis") or ""),
            adjusted_cost_per_share=(data.get("adjustedCostPerShare") or ""),
            acquired_or_opened_date=(data.get("acquiredOrOpenedDate") or ""),
            holding_period=(data.get("holdingPeriod") or ""),
            notes=(data.get("notes") or ""),
            event_id=str(data.get("eventId") or ""),
            raw_data=data,
        )


@dataclass
class UglPositionWithLots:
    """A position and its tax lots, from POST /cost-basis/ugl-position-lots/list
    (spec: UglPosition — named differently here to avoid colliding with the
    UglPosition summary record returned by GET /cost-basis/ugl-positions)."""

    position_id: str = ""
    lots: list[UglPositionLot] = field(default_factory=list)
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "UglPositionWithLots":
        return cls(
            position_id=(data.get("positionId") or ""),
            lots=[
                UglPositionLot.from_dict(lot)
                for lot in (data.get("lots") or [])
                if isinstance(lot, dict)
            ],
            raw_data=data,
        )


@dataclass
class UglPositionLotsResponse:
    """Response from POST /cost-basis/ugl-position-lots/list.

    Values are formatted strings. "N/A" indicates unavailable data.
    ``positions`` holds typed UglPositionWithLots records as of v0.3.0
    (previously raw dicts). Position IDs Schwab doesn't recognize come
    back in ``invalid_positions`` rather than as an error status.
    """

    positions: list[UglPositionWithLots] = field(default_factory=list)
    invalid_positions: list[str] = field(default_factory=list)
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "UglPositionLotsResponse":
        d = _unwrap_data(data)
        attrs = (d.get("attributes") or d)
        errors = (attrs.get("errors") or {})
        if not isinstance(errors, dict):
            errors = {}
        return cls(
            positions=[
                UglPositionWithLots.from_dict(p)
                for p in (attrs.get("positions") or [])
                if isinstance(p, dict)
            ],
            invalid_positions=(errors.get("invalidPositions") or []),
            raw_data=data,
        )


@dataclass
class CostBasisUglResponse:
    """Response from GET /cost-basis/ugl-positions.

    ``summary`` is a typed UglSummary as of v0.3.0 (previously a raw
    dict); the untyped payload is still on ``raw_data``.
    """

    summary: UglSummary | None = None
    positions: list[UglPosition] = field(default_factory=list)
    is_amortized: bool = False
    next_cursor: str | None = None
    total_count: int | None = None
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "CostBasisUglResponse":
        d = _unwrap_data(data)
        attrs = (d.get("attributes") or d)
        positions = [UglPosition.from_dict(p) for p in (attrs.get("positions") or [])]
        next_cursor, count = _parse_meta(data)
        summary = attrs.get("summary")
        return cls(
            summary=(
                UglSummary.from_dict(summary) if isinstance(summary, dict) else None
            ),
            positions=positions,
            is_amortized=bool(attrs.get("isAmortized") or False),
            next_cursor=next_cursor,
            total_count=count,
            raw_data=data,
        )


# --- Reports ---


@dataclass
class ReportsResponse:
    """Response from GET /reports."""

    reports: list[dict] = field(default_factory=list)
    next_cursor: str | None = None
    total_count: int | None = None
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "ReportsResponse":
        d = _unwrap_data(data)
        attrs = (d.get("attributes") or d)
        next_cursor, count = _parse_meta(data)
        return cls(
            reports=(attrs.get("reports") or []),
            next_cursor=next_cursor,
            total_count=count,
            raw_data=data,
        )


# --- Upload ManFees ---


@dataclass
class UploadResponse:
    """Response from POST /upload-manfees."""

    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "UploadResponse":
        return cls(raw_data=data)


# --- AS Feature Enrollment ---


@dataclass
class DataDeliveryEnrollmentResponse:
    """Response from GET /data-delivery-enrollments. Single boolean flag."""

    enrolled: bool = False
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "DataDeliveryEnrollmentResponse":
        d = _unwrap_data(data)
        attrs = (d.get("attributes") or d) if isinstance(d, dict) else {}
        return cls(
            enrolled=bool(attrs.get("enrolled") or False),
            raw_data=data,
        )


# --- AS Move Money Activity ---
#
# GET /as-integration/transfers/v1/activities (Schwab-Client-Ids: account=<acct>
# only — no masterAccount). Originally reverse-engineered from live sandbox
# responses; now matched to the official spec
# docs/schwab-move-money-activity-openapi.json (v2.0.0).


@dataclass
class MoveMoneyActivity:
    """A single money-movement item (wire, ACH, journal, check, transfer).

    Appears in the recurring / upcoming / recent buckets of the activities
    response. `frequency` is a Schwab code, e.g. "ONREQST" (one-time / on
    request) or "MONTHLY"; `direction` is "Outgoing"/"Incoming"; `status`
    e.g. "Pending". Recurring items carry `next_transaction_date` instead
    of `transaction_date`.
    """

    transaction_id: str = ""
    transaction_type: str = ""  # e.g. "Wire - 1st Party", "ACH", "Journal"
    direction: str = ""  # "Outgoing" / "Incoming"
    to_from: str = ""  # counter-party label, e.g. "Jpmorgan Chase  31903010"
    amount: float = 0.0
    transaction_date: str = ""  # ISO date "YYYY-MM-DD" (upcoming/recent)
    next_transaction_date: str = ""  # ISO date (recurring items only)
    frequency: str = ""  # e.g. "ONREQST"
    status: str = ""  # e.g. "Pending"
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "MoveMoneyActivity":
        return cls(
            transaction_id=str((data.get("transactionId") or "")),
            transaction_type=data.get("transactionType", "") or "",
            direction=data.get("direction", "") or "",
            to_from=data.get("toFrom", "") or "",
            amount=_safe_float(data, "amount"),
            transaction_date=data.get("transactionDate", "") or "",
            next_transaction_date=data.get("nextTransactionDate", "") or "",
            frequency=data.get("frequency", "") or "",
            status=data.get("status", "") or "",
            raw_data=data,
        )


@dataclass
class MoveMoneyActivitiesResponse:
    """Response from GET /activities (AS Move Money Activity).

    Groups a single account's money movements into three buckets:
    `recurring` (standing recurring transfers), `upcoming` (scheduled but not
    yet executed), and `recent` (executed/pending history).
    """

    formatted_account: str = ""
    recurring: list[MoveMoneyActivity] = field(default_factory=list)
    upcoming: list[MoveMoneyActivity] = field(default_factory=list)
    recent: list[MoveMoneyActivity] = field(default_factory=list)
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "MoveMoneyActivitiesResponse":
        d = _unwrap_data(data)
        attrs = (d.get("attributes") or d) if isinstance(d, dict) else {}

        def parse(key: str) -> list[MoveMoneyActivity]:
            return [MoveMoneyActivity.from_dict(x) for x in (attrs.get(key) or [])]

        return cls(
            formatted_account=attrs.get("formattedAccount", "") or "",
            recurring=parse("recurring"),
            upcoming=parse("upcoming"),
            recent=parse("recent"),
            raw_data=data,
        )


@dataclass
class TaxWithholdingElectionsResponse:
    """Response from GET /tax-withholding-elections (AS Move Money
    Activity v2). Election percentages are fractions (0.28 = 28%)."""

    formatted_account: str = ""
    is_tax_withholding_elected: bool = False
    is_federal_opted_out: bool = False
    federal_election: float = 0.0
    is_state_opted_out: bool = False
    state_election: float = 0.0
    state_code: str = ""
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "TaxWithholdingElectionsResponse":
        d = _unwrap_data(data)
        attrs = (d.get("attributes") or d) if isinstance(d, dict) else {}
        return cls(
            formatted_account=attrs.get("formattedAccount", "") or "",
            is_tax_withholding_elected=bool(attrs.get("isTaxWithholdingElected") or False),
            is_federal_opted_out=attrs.get(
                "isTaxWithholdingFederalOptedOut", False
            ),
            federal_election=_safe_float(attrs, "taxWithholdingElectionFederal"),
            is_state_opted_out=bool(attrs.get("isTaxWithholdingStateOptedOut") or False),
            state_election=_safe_float(attrs, "taxWithholdingElectionState"),
            state_code=attrs.get("taxWithholdingStateCode", "") or "",
            raw_data=data,
        )


# --- AS Move Money Transfers (transfers/v1, all POST/writes) ---
#
# Spec: docs/schwab-move-money-transfers-openapi.json (v1.0.0). Three
# routes that INITIATE real money movement: ACH via standing
# authorization, wire via standing authorization, free-form wire.


@dataclass
class TransferWarning:
    """Non-fatal warning attached to a 201 transfer response (meta.warnings)."""

    code: str = ""
    title: str = ""
    detail: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "TransferWarning":
        return cls(
            code=str((data.get("code") or "")),
            title=data.get("title", "") or "",
            detail=data.get("detail", "") or "",
        )


@dataclass
class RetirementDetails:
    """Retirement (IRA) facts on a transfer response: contribution/
    distribution coding plus computed tax-withholding amounts."""

    contribution_type_code: str = ""
    contribution_type_sub_code: str = ""
    distribution_reason: str = ""
    gross_net_indicator: str = ""  # "G" / "N"
    net_amount: float = 0.0
    federal_election: float = 0.0
    state_election: float = 0.0
    federal_withholding_amount: float = 0.0
    state_withholding_amount: float = 0.0
    total_withdrawal_amount: float = 0.0
    year: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "RetirementDetails":
        return cls(
            contribution_type_code=data.get("contributionTypeCode", "") or "",
            contribution_type_sub_code=data.get("contributionTypeSubCode", "") or "",
            distribution_reason=data.get("distributionReason", "") or "",
            gross_net_indicator=data.get("grossNetIndicator", "") or "",
            net_amount=_safe_float(data, "netAmount"),
            federal_election=_safe_float(data, "taxWithholdingElectionFederal"),
            state_election=_safe_float(data, "taxWithholdingElectionState"),
            federal_withholding_amount=_safe_float(
                data, "taxWithholdingFederalAmount"
            ),
            state_withholding_amount=_safe_float(data, "taxWithholdingStateAmount"),
            total_withdrawal_amount=_safe_float(data, "totalWithdrawalAmount"),
            year=str(data.get("year", "") or ""),
        )


@dataclass
class ToFromAccount:
    """Counterparty bank account on an ACH transfer response."""

    aba_number: str = ""
    account_name: str = ""
    account_type: str = ""
    financial_institution: str = ""
    formatted_account: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "ToFromAccount":
        return cls(
            aba_number=str(data.get("abaNumber", "") or ""),
            account_name=data.get("accountName", "") or "",
            account_type=data.get("accountType", "") or "",
            financial_institution=data.get("financialInstitution", "") or "",
            formatted_account=data.get("formattedAccount", "") or "",
        )


def _parse_transfer_warnings(data: dict) -> "list[TransferWarning]":
    meta = data.get("meta") or {}
    return [TransferWarning.from_dict(w) for w in (meta.get("warnings") or [])]


@dataclass
class AchTransferResponse:
    """201 response from POST /ach/standing-authorizations/{id}."""

    id: str = ""  # e.g. "A-7788990011-2023"
    amount: float = 0.0
    client_id: int | None = None
    direction: str = ""
    end_date: str = ""
    formatted_account: str = ""
    formatted_master_account: str = ""
    frequency: str = ""
    process_date: str = ""
    second_process_date: str = ""
    to_from_account: ToFromAccount | None = None
    retirement_details: RetirementDetails | None = None
    ptrs_details: dict | None = None
    warnings: list[TransferWarning] = field(default_factory=list)
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "AchTransferResponse":
        d = _unwrap_data(data)
        attrs = (d.get("attributes") or d) if isinstance(d, dict) else {}
        tfa = attrs.get("toFromAccount")
        ret = attrs.get("retirementResponseDetails")
        return cls(
            id=str((d.get("id") or "") if isinstance(d, dict) else ""),
            amount=_safe_float(attrs, "amount"),
            client_id=attrs.get("clientId"),
            direction=attrs.get("direction", "") or "",
            end_date=attrs.get("endDate", "") or "",
            formatted_account=attrs.get("formattedAccount", "") or "",
            formatted_master_account=attrs.get("formattedMasterAccount", "") or "",
            frequency=attrs.get("frequency", "") or "",
            process_date=attrs.get("processDate", "") or "",
            second_process_date=attrs.get("secondProcessDate", "") or "",
            to_from_account=ToFromAccount.from_dict(tfa) if tfa else None,
            retirement_details=RetirementDetails.from_dict(ret) if ret else None,
            ptrs_details=attrs.get("ptrsResponseDetails"),
            warnings=_parse_transfer_warnings(data),
            raw_data=data,
        )


@dataclass
class WireTransferResponse:
    """201 response from POST /wires or POST /wires/standing-authorizations/{id}.

    Bank/recipient/intermediary sub-objects are kept as raw dicts (their
    shapes vary by wire type); the commonly consumed scalars are typed.
    """

    id: str = ""
    case_id: str = ""
    status: str = ""
    submitted_by: str = ""
    submitted_date: str = ""
    amount: float = 0.0
    client_id: int | None = None
    process_date: str = ""
    wire_fee: float = 0.0
    transmission_note: str = ""
    account_details: dict | None = None
    recipient_bank_details: dict | None = None
    recipient_person_or_org_details: dict | None = None
    intermediary_details: dict | None = None
    second_intermediary_details: dict | None = None
    third_intermediary_details: dict | None = None
    standing_authorization_details: dict | None = None
    retirement_details: RetirementDetails | None = None
    ptrs_details: dict | None = None
    warnings: list[TransferWarning] = field(default_factory=list)
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "WireTransferResponse":
        d = _unwrap_data(data)
        attrs = (d.get("attributes") or d) if isinstance(d, dict) else {}
        ret = attrs.get("retirementResponseDetails")
        return cls(
            id=str((d.get("id") or "") if isinstance(d, dict) else ""),
            case_id=str(attrs.get("caseId", "") or ""),
            status=attrs.get("status", "") or "",
            submitted_by=attrs.get("submittedBy", "") or "",
            submitted_date=attrs.get("submittedDate", "") or "",
            amount=_safe_float(attrs, "amount"),
            client_id=attrs.get("clientId"),
            process_date=attrs.get("processDate", "") or "",
            wire_fee=_safe_float(attrs, "wireFee"),
            transmission_note=attrs.get("transmissionNote", "") or "",
            account_details=attrs.get("accountDetails"),
            recipient_bank_details=attrs.get("recipientBankDetails"),
            recipient_person_or_org_details=attrs.get(
                "recipientPersonOrOrgDetails"
            ),
            intermediary_details=attrs.get("intermediaryDetails"),
            second_intermediary_details=attrs.get("secondIntermediaryDetails"),
            third_intermediary_details=attrs.get("thirdIntermediaryDetails"),
            standing_authorization_details=attrs.get(
                "standingAuthorizationDetails"
            ),
            retirement_details=RetirementDetails.from_dict(ret) if ret else None,
            ptrs_details=attrs.get("ptrsResponseDetails"),
            warnings=_parse_transfer_warnings(data),
            raw_data=data,
        )


# --- AS User Authorization ---


@dataclass
class Authorization:
    """A single authorization grant. Schwab returns ~22 of these per user."""

    authorization: str = ""
    is_authorized: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> "Authorization":
        return cls(
            authorization=(data.get("authorization") or ""),
            is_authorized=bool(data.get("isAuthorized") or False),
        )


@dataclass
class UserAuthorizationsResponse:
    """Response from GET /authorizations.

    Sandbox: VERIFIED — returns ~22 authorization types and isUserFsa
    (firm security admin) flag for the calling user.
    """

    id: str = ""
    is_user_fsa: bool = False
    authorizations: list[Authorization] = field(default_factory=list)
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "UserAuthorizationsResponse":
        d = _unwrap_data(data)
        attrs = (d.get("attributes") or {}) if isinstance(d, dict) else {}
        return cls(
            id=(d.get("id") or "") if isinstance(d, dict) else "",
            is_user_fsa=bool(attrs.get("isUserFsa") or False),
            authorizations=[
                Authorization.from_dict(a) for a in (attrs.get("authorizations") or [])
            ],
            raw_data=data,
        )


# --- AS Trading ---


@dataclass
class OrderResult:
    """One per-order outcome from POST /orders, PUT /orders, DELETE /orders."""

    client_order_identifier: str = ""
    order_number: str = ""
    contingent_id: str = ""
    is_order_accepted: bool = False
    validation_errors: list[dict] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "OrderResult":
        return cls(
            client_order_identifier=(data.get("clientOrderIdentifier") or ""),
            order_number=(data.get("orderNumber") or ""),
            contingent_id=(data.get("contingentId") or ""),
            is_order_accepted=bool(data.get("isOrderAccepted") or False),
            validation_errors=(data.get("validationErrors") or []),
        )


@dataclass
class OrdersResponse:
    """Response from POST /orders, PUT /orders, DELETE /orders.

    Per-order results live on `order_results`; the top-level counts
    (`total_count`, `successful_count`, `fatal_error_count`,
    `informational_count`) summarize the batch.
    """

    id: str = ""
    type: str = ""
    total_count: int = 0
    successful_count: int = 0
    fatal_error_count: int = 0
    informational_count: int = 0
    order_results: list[OrderResult] = field(default_factory=list)
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "OrdersResponse":
        d = _unwrap_data(data)
        attrs = (d.get("attributes") or {}) if isinstance(d, dict) else {}
        return cls(
            id=(d.get("id") or "") if isinstance(d, dict) else "",
            type=(d.get("type") or "") if isinstance(d, dict) else "",
            total_count=_safe_int(attrs, "totalCount"),
            successful_count=_safe_int(attrs, "successfulCount"),
            fatal_error_count=_safe_int(attrs, "fatalErrorCount"),
            informational_count=_safe_int(attrs, "informationalCount"),
            order_results=[
                OrderResult.from_dict(r) for r in (attrs.get("orderResults") or [])
            ],
            raw_data=data,
        )


@dataclass
class OrderStatusDetail:
    """Order status detail returned by POST /orders/status.

    Union of CommonOrderStatusDetails + equity + mutual-fund fields.
    Equity orders populate cusip/quantity/limit_price/etc.; mutual-fund
    orders populate amount/price/lot_instructions/etc. Fields not
    relevant to the order's asset class default to empty / 0.
    """

    advisor_id: str = ""
    order_number: str = ""
    contingent_id: str = ""
    master_account: str = ""
    account: str = ""
    status: str = ""
    enter_date_time: str = ""
    symbol: str = ""
    # Equity-only
    cusip: str = ""
    quantity: float = 0.0
    actual_price: float = 0.0
    transaction_type: str = ""
    dividend_reinvestment: bool = False
    tax_lot_method: str = ""
    order_type: str = ""
    duration: str = ""
    limit_price: float = 0.0
    stop_price: float = 0.0
    trailing_stop_method: str = ""
    trailing_stop_amount: float = 0.0
    # Mutual-fund-only
    amount: float = 0.0
    price: float = 0.0
    amount_type: str = ""
    lot_instructions: list[dict] = field(default_factory=list)
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "OrderStatusDetail":
        return cls(
            advisor_id=(data.get("advisorId") or ""),
            order_number=str((data.get("orderNumber") or "")) if data.get("orderNumber") is not None else "",
            contingent_id=str((data.get("contingentId") or "")) if data.get("contingentId") is not None else "",
            master_account=str((data.get("masterAccount") or "")) if data.get("masterAccount") is not None else "",
            account=str((data.get("account") or "")) if data.get("account") is not None else "",
            status=(data.get("status") or ""),
            enter_date_time=(data.get("enterDateTime") or ""),
            symbol=(data.get("symbol") or ""),
            cusip=(data.get("cusip") or ""),
            quantity=_safe_float(data, "quantity"),
            actual_price=_safe_float(data, "actualPrice"),
            transaction_type=(data.get("transactionType") or ""),
            dividend_reinvestment=bool(data.get("dividendReinvestment") or False),
            tax_lot_method=(data.get("taxLotMethod") or ""),
            order_type=(data.get("orderType") or ""),
            duration=(data.get("duration") or ""),
            limit_price=_safe_float(data, "limitPrice"),
            stop_price=_safe_float(data, "stopPrice"),
            trailing_stop_method=(data.get("trailingStopMethod") or ""),
            trailing_stop_amount=_safe_float(data, "trailingStopAmount"),
            amount=_safe_float(data, "amount"),
            price=_safe_float(data, "price"),
            amount_type=(data.get("amountType") or ""),
            lot_instructions=(data.get("lotInstructions") or []),
            raw_data=data,
        )


@dataclass
class OrdersStatusResponse:
    """Response from POST /orders/status. Equity + mutual-fund details
    are returned in separate arrays."""

    id: str = ""
    type: str = ""
    total_orders: int = 0
    equity_order_status_details: list[OrderStatusDetail] = field(default_factory=list)
    mutual_fund_order_status_details: list[OrderStatusDetail] = field(
        default_factory=list
    )
    validation_errors: list[dict] = field(default_factory=list)
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "OrdersStatusResponse":
        d = _unwrap_data(data)
        attrs = (d.get("attributes") or {}) if isinstance(d, dict) else {}
        return cls(
            id=(d.get("id") or "") if isinstance(d, dict) else "",
            type=(d.get("type") or "") if isinstance(d, dict) else "",
            total_orders=_safe_int(attrs, "totalOrders"),
            equity_order_status_details=[
                OrderStatusDetail.from_dict(x)
                for x in (attrs.get("equityOrderStatusDetails") or [])
            ],
            mutual_fund_order_status_details=[
                OrderStatusDetail.from_dict(x)
                for x in (attrs.get("mutualFundOrderStatusDetails") or [])
            ],
            validation_errors=(attrs.get("validationErrors") or []),
            raw_data=data,
        )


# --- High-level facade: AccountSummary + AccountDetail ---
#
# These are NOT a Schwab response shape — they're convenience views
# composed from multiple endpoints by the facade methods on
# SchwabAdvisorClient (list_accounts, get_account_detail).
# Use them when you want "one call → useful answer" semantics; drop
# down to the raw client methods when you need control.


@dataclass
class AccountSummary:
    """Compact summary of one account, derived from AccountProfile.

    For listing/dropdown UIs. Use SchwabAdvisorClient.list_accounts() to
    fetch a list of these.
    """

    formatted_account: str = ""
    formatted_master_account: str = ""
    account_name: str = ""
    registration_type: str = ""
    restriction_codes: list[str] = field(default_factory=list)

    @classmethod
    def from_profile(cls, p: "AccountProfile") -> "AccountSummary":
        # accountTitle1 is the conventional "display name". Fall back to
        # subsequent title lines or empty string. Don't synthesize anything
        # the API didn't give us.
        name = p.title1 or p.title2 or p.title3 or ""
        return cls(
            formatted_account=p.formatted_account,
            formatted_master_account=p.formatted_master_account,
            account_name=name,
            registration_type=p.registration_type,
            restriction_codes=list(p.restriction_codes),
        )

    @classmethod
    def from_account_info(cls, a: "AccountInfo") -> "AccountSummary":
        """Build from Account Inquiry's AccountInfo (GET /accounts) — the
        fallback source when AS Account /account-profiles isn't attached
        to the app. AccountInfo.id is the spec's FormattedAccount.
        AccountInfo carries no restrictionCodes; that list stays empty."""
        name = a.title1 or a.title2 or a.title3 or ""
        return cls(
            formatted_account=a.id,
            formatted_master_account=a.formatted_master_account,
            account_name=name,
            registration_type=a.registration_type,
            restriction_codes=[],
        )


@dataclass
class AccountDetail:
    """All 1:1-with-account data for a single account, merged from
    AS Account, AS Account Preferences and Authorizations, AS Document
    Preferences, and (for IRAs) AS Account RMD.

    Beneficiaries / roles are 1:N — fetch separately with
    SchwabAdvisorClient.get_roles_for_account(). SLOAs are 1:N too —
    fetch with SchwabAdvisorClient.get_slas_for_account().
    """

    formatted_account: str = ""
    formatted_master_account: str = ""
    account_name: str = ""
    registration_type: str = ""
    profile: "AccountProfile | None" = None
    preferences_and_authorizations: "PreferencesAndAuthorizations | None" = None
    document_preferences: "DocumentPreference | None" = None
    rmd: "AccountRmd | None" = None


# --- AS Address Change (create response) ---


@dataclass
class AddressChangeCreateResponse:
    """Response from POST /address-changes.

    Sandbox returns 500 / times out (no real customer data); fields
    here are from the Schwab OpenAPI spec. The `id` is the new
    action ID; `envelope_id` is a Schwab-assigned envelope reference.
    """

    id: str = ""
    type: str = ""
    envelope_id: str = ""
    raw_data: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "AddressChangeCreateResponse":
        d = _unwrap_data(data)
        attrs = (d.get("attributes") or {}) if isinstance(d, dict) else {}
        return cls(
            id=(d.get("id") or "") if isinstance(d, dict) else "",
            type=(d.get("type") or "") if isinstance(d, dict) else "",
            envelope_id=(attrs.get("envelopeId") or ""),
            raw_data=data,
        )
