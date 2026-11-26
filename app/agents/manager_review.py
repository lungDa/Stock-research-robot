"""Ephemeral, session-bound simulation records; no raw snapshot retention."""
from datetime import datetime,timezone
from app.agents.recovery_policy import fresh
from hashlib import sha256
from threading import RLock
from collections import OrderedDict
from uuid import uuid4
import time,re,json
from copy import deepcopy
from app.agents.supervisor import Supervisor

# Fixed vocabulary from trusted agent implementations; never learned from snapshots.
_REPORT_WORDS = frozenset("__shadow__ _basis _close _evidence _previous _unknown acceptance accepted_messages accepted_request_id action adjusted_close adjustment_factor adjustment_source_url adjustment_status advice alignment annual_evidence annual_paid annual_volatility api_accepted_only api_health api_ready approval approval_required approval_state approve approved approved_at approved_version as_of at attempts audit authorization_error available average_daily_value_twd bars basis benchmark benchmark_id benchmark_levels benchmark_published_at benchmark_source_url beta beta_basis beta_stress_returns blocked blocked_by_dependency breaches busy calendar_known caller_assumed_pe_sensitivity_not_fair_value caller_metadata_checked capital_expenditure cash_dividend_per_share cash_dividend_years cash_dividends_paid cash_weight cash_yield_pct cashflow_basis category checks circuit classification classification_scope classification_verified cleared close closed code collect_evidence collector comparison compensation complete complete_items completed component_confidence confidence confidence_basis config_hash conflicts cooldown correlation counts coverage coverage_ratio created_at critical currency current current_subscribers_and_cached_outboxes daily_scan data data_conflict data_missing data_status database database_dependency_hypothesis database_unknown database_unready date defensive delay_seconds delivery_verified denied distinct_origin_conflicts dividend_basis do_not_resend document documents down_sessions downside_beta duplicate_retry_keys duplicate_risk eligible eligible_users enabled eps eps_basis eps_published_at equity error errors etf evening event events evidence evidence_version executed execution_allowed expected_items expense_ratio expired_or_unknown exposure factors failed_jobs failures fcf field field_sources financial financial_audit financial_evidence_issue financial_refresh four_rankings fresh_independent_audit_required fundamentals_only half_open high historical_pe historical_scenario historical_scope history hold_and_review holdings http http_status https id illustrative_no_market_impact incident income incomplete index info inner input_digest inspect_notification_evidence inspect_service_dependencies insufficient_data insufficient_down_sessions invalid invalid_snapshot jobs key kind larger_sample_not_calibrated last_at level limit_breach limited limits liquidity low manual_preview_or_send manual_review market market_risk max_drawdown messages method metrics missing_fields missing_years mode monitor morning multiples nan negative_latest_annual_eps net_asset_weight next_attempt next_offset not_applicable_etf not_verified notification notification_accepted notification_duplicate notification_failure notification_pending observed observed_at ok one_level_long_only_snapshot one_level_snapshot_lookthrough open opened_at operating_cash_flow operation operations origin original_filing_id outbox outbox_digest outbox_review overlaps paid paid_common_cash_dividends pairs partial pe pending period_end plan planned plans portfolio_metrics position positions possible_missing previous price price_date price_source probe provisional_rule_coverage_not_return_probability published_at quality_score quantity quota_exhausted quote ranking_workflow rate_limited raw_ raw_close raw_price raw_volume reason receipt_uncertain recommendations reconcile_source_evidence redacted refresh_workflow reject rejected relative_volume released_before_taiwan_open repair_priority report reported_multiple_not_fair_value reports request_id requested_at requested_symbols_only required_missing research research_coverage_insufficient research_only research_version retry retry_key return returns revenue review_evidence review_existing_repair_queue review_existing_retry_keys revoke revoked risk_grade risk_only roe_pct root_cause rows rule_score_comparison_not_trade_ranking same_day same_filing_conflicts sample_id samples scan_workflow scenario schedule schema_version scope score sector sector_evidence sector_scope sector_unconfirmed sector_weights sectors sent series session_expired severity shadow shares simulate_ simulate_failure simulate_probe simulate_probe_failure simulate_probe_success simulated_improvement single slot snapshot_at snapshot_percentiles_not_fair_value source source_url sox stale stale_jobs stale_sources state status stock stock_code_and_quote_only stock_observed_at stock_source_url stress_returns swing symbol symbols system_failure system_warning taiex_beta tail_confidence tail_samples target technical timeout total total_count total_return trigger ttm type unconfirmed underlying unit unknown unknown_schedule unknown_sources unknown_weight unresolved_provenance_conflicts upstream_error upstream_wakeup valuation value verification verified verify_subscription_and_schedule version volatility volume_ratio volume_unit warning warnings weight weighted_five_benchmark_proxy weights within_configured_limits workflow_dispatch workflow_run year years yield".split())
_DIGEST_FIELDS = frozenset("snapshot_digest input_digest evidence_version research_version id plan operation".split())
_DATE_FIELDS = frozenset("observed_at at date".split())

def safe_report(value, field=None):
    # Allowlisted structural keys; omit arbitrary text, URLs, user IDs and receipts.
    keys=set("mode status execution_allowed executed report snapshot_digest observed_at rows history plans findings code severity symbol scope category action id evidence_version approval_state weights cash_weight risk_grade portfolio_metrics samples annualized_volatility annual_volatility tail_samples max_drawdown var95_daily cvar95_daily confidence factors score coverage complete_items expected_items quality_score counts checks conflicts invalid stale_sources unknown_sources duplicate_retry_keys duplicate_risk receipt_uncertain pending partial possible_missing expired_or_unknown api_accepted_only research_version input_digest component_confidence market financial_audit positions warnings blocked_by_dependency approval_required events event plan operation at date slot accepted_messages retry circuit state delay_seconds source root_cause verification verified delivery_verified".split())
    if isinstance(value,dict):
        return {k:safe_report(v,k) for k,v in value.items() if k in keys or re.fullmatch(r"[0-9]{4,6}\.TW[O]?",k)}
    if isinstance(value,list):return [safe_report(v,field) for v in value[:500]]
    if isinstance(value,str):
        if field in _DIGEST_FIELDS and re.fullmatch(r"[a-f0-9]{64}",value):return value
        if field in _DATE_FIELDS and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}(?:T[0-9:.+Z-]+)?",value):
            try:datetime.fromisoformat(value.replace("Z","+00:00"))
            except ValueError:return "[redacted]"
            return value
        if field in ("symbol","scope") and re.fullmatch(r"[0-9]{4,6}\.TW[O]?",value):return value
        return value if value in _REPORT_WORDS else "[redacted]"
    return value if value is None or type(value) in (bool,int,float) else None

class ReviewStore:
    def __init__(self):
        self.lock=RLock()
        self.sessions=OrderedDict()
    def _session(self,user,token):
        now=time.monotonic()
        for k in list(self.sessions):
            if now-self.sessions[k]["at"]>900:del self.sessions[k]
        key=sha256((str(user)+"\0"+token).encode()).hexdigest()
        if key not in self.sessions:
            if len(self.sessions)>=32:self.sessions.popitem(last=False)
            self.sessions[key]={"at":now,"runs":[],"sim":None,"review_id":None,"plans":[],"evidence":{}}
        return self.sessions[key]
    def clear(self,user,token):
        with self.lock:
            self.sessions.pop(sha256((str(user)+"\0"+token).encode()).hexdigest(),None)
    def begin(self,user,token):
        with self.lock:return self._session(user,token)
    def record(self,user,token,name,result,payload,expected=None):
        with self.lock:
            if expected is not None and (self.sessions.get(sha256((str(user)+"\0"+token).encode()).hexdigest()) is not expected or time.monotonic()-expected["at"]>900):
                return {"mode":"shadow","execution_allowed":False,"status":"session_expired"}
            s=self._session(user,token)
            now=datetime.now(timezone.utc)
            clean=safe_report(result)
            if isinstance(clean.get("report"),dict) and clean.get("observed_at"):
                clean["report"]["observed_at"]=clean["observed_at"]
                clean["report"]["snapshot_digest"]=clean.get("snapshot_digest")
            source={"system_monitor":"monitor","data_auditor":"data","notification":"notification"}.get(name)
            if source:
                # Any refreshed evidence invalidates the previous review atomically.
                s.update(sim=None,review_id=None,plans=[],reviewable=set())
                s["evidence"].pop(source,None)
                if isinstance(clean.get("report"),dict) and clean.get("observed_at") and clean.get("snapshot_digest"):
                    s["evidence"][source]=deepcopy(clean["report"])
            if name=="recovery":
                s.update(sim=None,review_id=None,plans=[])
                if result.get("report",{}).get("status")=="planned":
                    sim=Supervisor(enabled=True).recovery_simulation(is_admin=True)
                    incident=uuid4().hex
                    evidence={}
                    for k in ("monitor","data","notification"):
                        report=s["evidence"].get(k)
                        if report is None or payload.get(k)!=report:continue
                        try:at=datetime.fromisoformat(report["observed_at"])
                        except (TypeError,KeyError,ValueError):continue
                        if fresh(at,now):evidence[k]={"source":k,"at":at,"report":report}
                    if not evidence or any(payload.get(k) is not None and k not in evidence for k in ("monitor","data","notification")):
                        clean["report"]["review_status"]="missing_fresh_evidence"
                        return clean
                    p=sim.plan(incident=incident,now=now,evidence=evidence)
                    s.update(sim=sim,review_id=incident,plans=safe_report(p["plans"]))
                    s["reviewable"]={x["id"] for x in p["plans"] if x["source"] in evidence and x["category"]!="unknown"}
                    clean["review_id"]=incident
                    clean["report"]["plans"]=s["plans"]
            s["runs"]=(s["runs"]+[{"agent":name,"at":now.isoformat(),"status":clean.get("report",{}).get("status",clean.get("status","unknown")),"snapshot_digest":clean.get("snapshot_digest")}])[-100:]
            return clean
    def review(self,user,token,p):
        with self.lock:
            s=self._session(user,token)
            if not s["sim"] or p.get("review_id")!=s["review_id"] or p.get("event") not in ("approve","reject","revoke"):return False
            if not all(isinstance(p.get(k),str) and 0<len(p[k])<=128 for k in ("plan","version","operation_id","review_id")):return False
            if p.get("plan") not in s.get("reviewable",set()):return False
            if not any(x["id"]==p.get("plan") and x["evidence_version"]==p.get("version") for x in s["plans"]):return False
            return s["sim"].transition(p["plan"],p["event"],datetime.now(timezone.utc),operation_id=p.get("operation_id"),expected_version=p["version"])
    def history(self,user,token):
        with self.lock:
            s=self._session(user,token)
            return {"mode":"shadow","execution_allowed":False,"runs":list(s["runs"]),"review":safe_report(s["sim"].export_history()) if s["sim"] else None}
