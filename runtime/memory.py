"""
WorkGraph Memory & Knowledge Subsystem (SQLite FTS5)
Stores documents, compiled rules, vendor profiles, decisions, and versioned playbooks.
Every memory item has strict provenance (user_provided, document_extracted, execution_verified).
Implements the 'Learn from Approval' mechanism for autonomous adaptation.
"""

import sqlite3
import json
import os
from typing import List, Dict, Any, Optional
from datetime import datetime

from runtime.contracts import Rule, RuleCondition, RuleAction, ProvenanceKind

MEMORY_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "memory.db")


def get_memory_db():
    os.makedirs(os.path.dirname(MEMORY_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(MEMORY_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_memory():
    conn = get_memory_db()
    cursor = conn.cursor()

    # Documents & SOPs with full-text search
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS documents (
        doc_id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        category TEXT NOT NULL,
        provenance TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)

    # FTS5 virtual table for keyword retrieval
    cursor.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
        doc_id UNINDEXED,
        title,
        content
    )
    """)

    # Compiled SOP and Exception Rules
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS rules (
        rule_id TEXT PRIMARY KEY,
        source_doc TEXT NOT NULL,
        source_quote TEXT NOT NULL,
        condition_json TEXT NOT NULL,
        action TEXT NOT NULL,
        reason TEXT NOT NULL,
        provenance TEXT NOT NULL,
        approved_by TEXT,
        version INTEGER DEFAULT 1,
        created_at TEXT NOT NULL
    )
    """)

    # Decisions log (e.g. human approval decisions and exception learnings)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS decisions (
        decision_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        subject TEXT NOT NULL,
        decision TEXT NOT NULL,
        reason TEXT,
        exception_rule_id TEXT,
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)

    # Versioned Playbooks
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS playbooks (
        playbook_id TEXT,
        version INTEGER,
        workflow_type TEXT NOT NULL,
        plan_json TEXT NOT NULL,
        success_count INTEGER DEFAULT 0,
        provenance TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (playbook_id, version)
    )
    """)

    conn.commit()
    conn.close()

init_memory()


class CompanyMemory:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or MEMORY_DB_PATH

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def store_document(self, doc_id: str, title: str, content: str, category: str = "policy",
                       provenance: ProvenanceKind = ProvenanceKind.USER_PROVIDED):
        conn = self._conn()
        cursor = conn.cursor()
        created_at = datetime.now().isoformat()
        cursor.execute("""
        INSERT OR REPLACE INTO documents (doc_id, title, content, category, provenance, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (doc_id, title, content, category, provenance.value, created_at))
        
        # Sync to FTS5
        cursor.execute("DELETE FROM documents_fts WHERE doc_id = ?", (doc_id,))
        cursor.execute("INSERT INTO documents_fts (doc_id, title, content) VALUES (?, ?, ?)",
                       (doc_id, title, content))
        conn.commit()
        conn.close()

    def search_documents(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        conn = self._conn()
        cursor = conn.cursor()
        # Clean query for FTS5 syntax
        clean_q = " ".join([w for w in query.replace('"', '').replace("'", "").split() if w.isalnum()])
        if not clean_q:
            cursor.execute("SELECT * FROM documents LIMIT ?", (limit,))
        else:
            cursor.execute("""
            SELECT d.doc_id, d.title, d.content, d.category, d.provenance
            FROM documents_fts f
            JOIN documents d ON f.doc_id = d.doc_id
            WHERE documents_fts MATCH ?
            LIMIT ?
            """, (clean_q, limit))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def store_rule(self, rule: Rule, provenance: ProvenanceKind = ProvenanceKind.USER_PROVIDED):
        conn = self._conn()
        cursor = conn.cursor()
        cursor.execute("""
        INSERT OR REPLACE INTO rules (rule_id, source_doc, source_quote, condition_json, action, reason, provenance, approved_by, version, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            rule.id,
            rule.source_doc,
            rule.source_quote,
            json.dumps(rule.condition.dict()),
            rule.action.value,
            rule.reason,
            provenance.value,
            rule.approved_by,
            rule.version,
            datetime.now().isoformat()
        ))
        conn.commit()
        conn.close()

    def get_all_rules(self) -> List[Rule]:
        conn = self._conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM rules ORDER BY version DESC")
        rows = cursor.fetchall()
        conn.close()

        rules = []
        for r in rows:
            cond_data = json.loads(r["condition_json"])
            rules.append(Rule(
                id=r["rule_id"],
                source_doc=r["source_doc"],
                source_quote=r["source_quote"],
                condition=RuleCondition(**cond_data),
                action=RuleAction(r["action"]),
                reason=r["reason"],
                approved_by=r["approved_by"],
                version=r["version"]
            ))
        return rules

    def store_decision(self, decision_id: str, run_id: str, subject: str, decision: str,
                       reason: Optional[str] = None, exception_rule_id: Optional[str] = None,
                       created_by: str = "human_supervisor"):
        conn = self._conn()
        cursor = conn.cursor()
        cursor.execute("""
        INSERT OR REPLACE INTO decisions (decision_id, run_id, subject, decision, reason, exception_rule_id, created_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (decision_id, run_id, subject, decision, reason, exception_rule_id, created_by, datetime.now().isoformat()))
        conn.commit()
        conn.close()

    def learn_exception_from_approval(self, run_id: str, vendor_id: str, max_allowed_variance_pct: float, 
                                      approver: str = "finance_director", notes: Optional[str] = None) -> Rule:
        """
        Demo Moment: Approver confirms an exception for a vendor.
        Stores a high-priority exception rule with provenance=user_provided.
        Next time an invoice from this vendor has <= max_allowed_variance_pct, it passes automatically!
        """
        rule_id = f"EXCEPTION_RULE_{vendor_id.replace('-', '_')}"
        reason = f"Learned Exception: Authorized surcharge/variance up to {max_allowed_variance_pct:.1f}% for {vendor_id}. Approved by {approver}."
        if notes:
            reason += f" Notes: {notes}"

        exception_rule = Rule(
            id=rule_id,
            source_doc="human_approval_decision",
            source_quote=f"Approved exception for {vendor_id} up to {max_allowed_variance_pct}% variance",
            condition=RuleCondition(
                field=f"vendor_variance:{vendor_id}",
                op="<=",
                value=max_allowed_variance_pct
            ),
            action=RuleAction.PASS,
            reason=reason,
            approved_by=approver,
            version=1
        )

        self.store_rule(exception_rule, provenance=ProvenanceKind.USER_PROVIDED)
        self.store_decision(
            decision_id=f"DEC-{run_id}-{vendor_id}",
            run_id=run_id,
            subject=f"Exception approval for {vendor_id}",
            decision="APPROVED_WITH_EXCEPTION",
            reason=reason,
            exception_rule_id=rule_id,
            created_by=approver
        )
        return exception_rule

    def get_playbook(self, workflow_type: str) -> Optional[Dict[str, Any]]:
        conn = self._conn()
        cursor = conn.cursor()
        cursor.execute("""
        SELECT plan_json, version FROM playbooks
        WHERE workflow_type = ?
        ORDER BY version DESC LIMIT 1
        """, (workflow_type,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return json.loads(row["plan_json"])
        return None

    def save_playbook(self, playbook_id: str, workflow_type: str, plan_dict: Dict[str, Any], version: int = 1):
        conn = self._conn()
        cursor = conn.cursor()
        cursor.execute("""
        INSERT OR REPLACE INTO playbooks (playbook_id, version, workflow_type, plan_json, provenance, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (playbook_id, version, workflow_type, json.dumps(plan_dict), ProvenanceKind.EXECUTION_VERIFIED.value, datetime.now().isoformat()))
        conn.commit()
        conn.close()

    def clear_exceptions(self):
        """Clears all learned exception rules and approval decisions."""
        conn = self._conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM rules WHERE rule_id LIKE 'EXCEPTION_RULE_%'")
        cursor.execute("DELETE FROM decisions")
        conn.commit()
        conn.close()
