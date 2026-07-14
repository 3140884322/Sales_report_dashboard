from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence

import pandas as pd

from relationship_models import (
    ApprovedJoinPlan,
    ApprovedJoinStep,
    MergeStepDiagnostic,
    RelationshipCandidate,
    RelationshipDecision,
    RelationshipDiscoveryResult,
    SafeMergeResult,
)
from relationship_safety import canonicalize_key_series, evaluate_join_safety


class RelationshipApprovalError(ValueError):
    """Raised when a blocked relationship is explicitly approved."""


class JoinPlanValidationError(ValueError):
    """Raised when approved relationships do not form a safe rooted plan."""

    def __init__(self, errors: Sequence[str]):
        self.errors = tuple(errors)
        super().__init__(" ".join(self.errors))


def pending_relationship(candidate: RelationshipCandidate) -> RelationshipDecision:
    return RelationshipDecision(
        original_candidate_id=candidate.candidate_id,
        status="pending",
        candidate=candidate,
    )


def approve_relationship(
    candidate: RelationshipCandidate,
    original_candidate_id: str | None = None,
    edited: bool = False,
) -> RelationshipDecision:
    """Create an explicit approval; blocked candidates can never be approved."""
    if candidate.blocked:
        reasons = " ".join(candidate.block_reasons) or "Safety checks blocked it."
        raise RelationshipApprovalError(
            f"Blocked relationship cannot be approved. {reasons}"
        )
    return RelationshipDecision(
        original_candidate_id=original_candidate_id or candidate.candidate_id,
        status="approved",
        candidate=candidate,
        edited=edited,
    )


def reject_relationship(
    candidate: RelationshipCandidate,
    original_candidate_id: str | None = None,
    edited: bool = False,
) -> RelationshipDecision:
    return RelationshipDecision(
        original_candidate_id=original_candidate_id or candidate.candidate_id,
        status="rejected",
        candidate=candidate,
        edited=edited,
    )


def edit_relationship(
    original_candidate: RelationshipCandidate,
    edited_candidate: RelationshipCandidate,
) -> RelationshipDecision:
    """Record a re-evaluated edit as pending until the user approves it."""
    return RelationshipDecision(
        original_candidate_id=original_candidate.candidate_id,
        status="pending",
        candidate=edited_candidate,
        edited=True,
    )


def _decision_values(decisions) -> list[RelationshipDecision]:
    if isinstance(decisions, Mapping):
        values = list(decisions.values())
    else:
        values = list(decisions)
    if not all(isinstance(value, RelationshipDecision) for value in values):
        raise JoinPlanValidationError(
            ["Approved join plan decisions must be RelationshipDecision objects."]
        )
    return values


def _step_from_decision(
    decision: RelationshipDecision,
    step_number: int,
) -> ApprovedJoinStep:
    candidate = decision.candidate
    return ApprovedJoinStep(
        step_id=f"join_{step_number}",
        source_candidate_id=decision.original_candidate_id,
        left_table_id=candidate.left_table_id,
        left_table=candidate.left_table,
        left_columns=candidate.left_columns,
        right_table_id=candidate.right_table_id,
        right_table=candidate.right_table,
        right_columns=candidate.right_columns,
        comparison_kinds=candidate.comparison_kinds,
        confidence_score=candidate.confidence_score,
        match_rate=candidate.match_rate,
        right_key_uniqueness=candidate.right_key_uniqueness,
        expected_join_type=candidate.expected_join_type,
        edited=decision.edited,
    )


def _graph_has_cycle(steps: Sequence[ApprovedJoinStep]) -> bool:
    adjacency: dict[str, list[str]] = defaultdict(list)
    for step in steps:
        adjacency[step.left_table_id].append(step.right_table_id)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(table_id: str) -> bool:
        if table_id in visiting:
            return True
        if table_id in visited:
            return False
        visiting.add(table_id)
        for neighbor in adjacency.get(table_id, []):
            if visit(neighbor):
                return True
        visiting.remove(table_id)
        visited.add(table_id)
        return False

    return any(visit(table_id) for table_id in tuple(adjacency))


def validate_join_steps(
    discovery_result: RelationshipDiscoveryResult,
    fact_table_id: str | None,
    steps: Sequence[ApprovedJoinStep],
) -> tuple[tuple[ApprovedJoinStep, ...], tuple[str, ...]]:
    """Validate and topologically order a fact-rooted dimension expansion graph."""
    errors: list[str] = []
    table_ids = {table.table_id for table in discovery_result.tables}
    if not fact_table_id:
        return (), ("A fact table must be explicitly selected.",)
    if fact_table_id not in table_ids:
        return (), (f"Selected fact table {fact_table_id!r} does not exist.",)
    if not steps:
        if len(discovery_result.tables) == 1:
            return (), ()
        return (), ("At least one relationship must be explicitly approved.",)

    for step in steps:
        if step.left_table_id not in table_ids or step.right_table_id not in table_ids:
            errors.append(f"Step {step.step_id} references an unknown table.")
        if step.left_table_id == step.right_table_id:
            errors.append(f"Step {step.step_id} joins a table to itself.")
        if step.right_table_id == fact_table_id:
            errors.append(
                f"Step {step.step_id} points back to the selected fact table."
            )
        if step.right_key_uniqueness < 1.0:
            errors.append(
                f"Step {step.step_id} right key is not unique and cannot use many-to-one."
            )
        if step.expected_join_type not in {"many_to_one", "one_to_one"}:
            errors.append(
                f"Step {step.step_id} expects {step.expected_join_type}, not many-to-one."
            )

    duplicate_targets = [
        table_id
        for table_id, count in Counter(step.right_table_id for step in steps).items()
        if count > 1
    ]
    if duplicate_targets:
        errors.append(
            "The same dimension table cannot be merged more than once: "
            + ", ".join(sorted(duplicate_targets))
            + "."
        )
    if _graph_has_cycle(steps):
        errors.append("Approved relationships contain a cycle.")
    if errors:
        return (), tuple(dict.fromkeys(errors))

    connected = {fact_table_id}
    remaining = list(steps)
    ordered: list[ApprovedJoinStep] = []
    while remaining:
        progressed = False
        for step in tuple(remaining):
            if step.left_table_id in connected and step.right_table_id not in connected:
                ordered.append(step)
                connected.add(step.right_table_id)
                remaining.remove(step)
                progressed = True
        if not progressed:
            disconnected = ", ".join(step.step_id for step in remaining)
            errors.append(
                "Every relationship must expand from the fact table or an already "
                f"connected table. Unreachable step(s): {disconnected}."
            )
            break

    return tuple(ordered) if not errors else (), tuple(errors)


def build_approved_join_plan(
    discovery_result: RelationshipDiscoveryResult,
    fact_table_id: str | None,
    decisions,
) -> ApprovedJoinPlan:
    """Build a validated plan from explicit approvals; pending/rejected items are ignored."""
    values = _decision_values(decisions)
    approved = [decision for decision in values if decision.status == "approved"]
    errors: list[str] = []
    for decision in approved:
        candidate = decision.candidate
        if candidate.blocked:
            errors.append(
                f"Blocked relationship {decision.original_candidate_id} cannot enter the plan."
            )
        if candidate.right_key_uniqueness < 1.0:
            errors.append(
                f"Relationship {decision.original_candidate_id} has a non-unique right key."
            )
    if errors:
        raise JoinPlanValidationError(errors)

    raw_steps = tuple(
        _step_from_decision(decision, index)
        for index, decision in enumerate(approved, start=1)
    )
    ordered_steps, validation_errors = validate_join_steps(
        discovery_result, fact_table_id, raw_steps
    )
    if validation_errors:
        raise JoinPlanValidationError(validation_errors)

    fact_table = discovery_result.get_table(str(fact_table_id))
    renumbered = tuple(
        ApprovedJoinStep(
            step_id=f"join_{index}",
            source_candidate_id=step.source_candidate_id,
            left_table_id=step.left_table_id,
            left_table=step.left_table,
            left_columns=step.left_columns,
            right_table_id=step.right_table_id,
            right_table=step.right_table,
            right_columns=step.right_columns,
            comparison_kinds=step.comparison_kinds,
            confidence_score=step.confidence_score,
            match_rate=step.match_rate,
            right_key_uniqueness=step.right_key_uniqueness,
            expected_join_type=step.expected_join_type,
            edited=step.edited,
        )
        for index, step in enumerate(ordered_steps, start=1)
    )
    return ApprovedJoinPlan(
        fact_table_id=fact_table.table_id,
        fact_table=fact_table.table_name,
        steps=renumbered,
        validation_status="valid",
    )


def _unique_column_name(base_name: str, used_names: set[str]) -> str:
    candidate = base_name
    suffix = 2
    while candidate in used_names:
        candidate = f"{base_name}#{suffix}"
        suffix += 1
    used_names.add(candidate)
    return candidate


def _failure_result(
    plan: ApprovedJoinPlan,
    fact_rows: int,
    diagnostics: list[MergeStepDiagnostic],
    message: str,
) -> SafeMergeResult:
    return SafeMergeResult(
        success=False,
        fact_table_id=plan.fact_table_id,
        fact_table=plan.fact_table,
        fact_row_count=fact_rows,
        final_row_count=None,
        merged_frame=None,
        diagnostics=tuple(diagnostics),
        error_message=message,
    )


def execute_approved_join_plan(
    discovery_result: RelationshipDiscoveryResult,
    plan: ApprovedJoinPlan,
) -> SafeMergeResult:
    """Execute a validated plan with normalized keys and validate='many_to_one'."""
    ordered_steps, errors = validate_join_steps(
        discovery_result, plan.fact_table_id, plan.steps
    )
    fact_table = discovery_result.get_table(plan.fact_table_id)
    fact_rows = int(len(fact_table.frame))
    if errors:
        return _failure_result(plan, fact_rows, [], " ".join(errors))

    profile_by_id = {
        profile.table_id: profile for profile in discovery_result.table_profiles
    }
    merged = fact_table.frame.copy()
    lineage = {
        (fact_table.table_id, column): column for column in fact_table.frame.columns
    }
    diagnostics: list[MergeStepDiagnostic] = []

    for step_index, step in enumerate(ordered_steps, start=1):
        right_table = discovery_result.get_table(step.right_table_id)
        try:
            resolved_left_columns = tuple(
                lineage[(step.left_table_id, column)] for column in step.left_columns
            )
        except KeyError as error:
            message = (
                f"Step {step.step_id} cannot resolve connected source column "
                f"{error.args[0]!r}."
            )
            diagnostics.append(
                MergeStepDiagnostic(
                    step_id=step.step_id,
                    left_table=step.left_table,
                    right_table=step.right_table,
                    left_columns=step.left_columns,
                    right_columns=step.right_columns,
                    rows_before=len(merged),
                    rows_after=None,
                    matched_rows=None,
                    unmatched_rows=None,
                    match_rate=None,
                    row_growth=None,
                    validation_status="failed_lineage",
                    error_message=message,
                )
            )
            return _failure_result(plan, fact_rows, diagnostics, message)

        safety = evaluate_join_safety(
            merged,
            right_table.frame,
            resolved_left_columns,
            step.right_columns,
            step.comparison_kinds,
            profile_by_id[step.left_table_id].role_guess,
            profile_by_id[step.right_table_id].role_guess,
            profile_by_id[step.left_table_id].entity_role,
            profile_by_id[step.right_table_id].entity_role,
        )
        if safety.blocked or safety.right_key_uniqueness < 1.0:
            message = " ".join(safety.block_reasons) or "Right key is not unique."
            matched_rows = int(round(safety.match_rate * safety.before_row_count))
            diagnostics.append(
                MergeStepDiagnostic(
                    step_id=step.step_id,
                    left_table=step.left_table,
                    right_table=step.right_table,
                    left_columns=step.left_columns,
                    right_columns=step.right_columns,
                    rows_before=safety.before_row_count,
                    rows_after=safety.after_row_count,
                    matched_rows=matched_rows,
                    unmatched_rows=safety.before_row_count - matched_rows,
                    match_rate=safety.match_rate,
                    row_growth=safety.row_count_change,
                    validation_status="blocked_preflight",
                    error_message=message,
                )
            )
            return _failure_result(plan, fact_rows, diagnostics, message)

        used_names = set(merged.columns)
        right_column_names = {
            column: _unique_column_name(
                f"{right_table.table_id}.{column}", used_names
            )
            for column in right_table.frame.columns
        }
        right_prepared = right_table.frame.rename(columns=right_column_names).copy()
        left_prepared = merged.copy()
        left_temp_keys: list[str] = []
        right_temp_keys: list[str] = []
        for key_index, (left_column, right_column, kind) in enumerate(
            zip(resolved_left_columns, step.right_columns, step.comparison_kinds),
            start=1,
        ):
            left_temp = _unique_column_name(
                f"__generic_join_{step_index}_left_{key_index}", used_names
            )
            right_temp = _unique_column_name(
                f"__generic_join_{step_index}_right_{key_index}", used_names
            )
            left_prepared[left_temp] = canonicalize_key_series(
                merged[left_column], kind
            )
            right_prepared[right_temp] = canonicalize_key_series(
                right_table.frame[right_column], kind
            )
            left_temp_keys.append(left_temp)
            right_temp_keys.append(right_temp)

        indicator_name = _unique_column_name(
            f"__generic_join_{step_index}_status", used_names
        )
        rows_before = int(len(left_prepared))
        try:
            next_frame = left_prepared.merge(
                right_prepared,
                how="left",
                left_on=left_temp_keys,
                right_on=right_temp_keys,
                sort=False,
                indicator=indicator_name,
                validate="many_to_one",
                copy=False,
            )
        except pd.errors.MergeError as error:
            message = f"many_to_one validation failed at {step.step_id}: {error}"
            diagnostics.append(
                MergeStepDiagnostic(
                    step_id=step.step_id,
                    left_table=step.left_table,
                    right_table=step.right_table,
                    left_columns=step.left_columns,
                    right_columns=step.right_columns,
                    rows_before=rows_before,
                    rows_after=None,
                    matched_rows=None,
                    unmatched_rows=None,
                    match_rate=None,
                    row_growth=None,
                    validation_status="failed_many_to_one",
                    error_message=message,
                )
            )
            return _failure_result(plan, fact_rows, diagnostics, message)

        rows_after = int(len(next_frame))
        row_growth = rows_after - rows_before
        matched_rows = int((next_frame[indicator_name] == "both").sum())
        unmatched_rows = int((next_frame[indicator_name] == "left_only").sum())
        match_rate = float(matched_rows / rows_before) if rows_before else 0.0
        validation_status = "passed" if row_growth == 0 else "failed_row_growth"
        message = ""
        if row_growth > 0:
            message = (
                f"Row growth detected at {step.step_id}: "
                f"{rows_before} -> {rows_after} (+{row_growth})."
            )

        diagnostics.append(
            MergeStepDiagnostic(
                step_id=step.step_id,
                left_table=step.left_table,
                right_table=step.right_table,
                left_columns=step.left_columns,
                right_columns=step.right_columns,
                rows_before=rows_before,
                rows_after=rows_after,
                matched_rows=matched_rows,
                unmatched_rows=unmatched_rows,
                match_rate=match_rate,
                row_growth=row_growth,
                validation_status=validation_status,
                error_message=message,
            )
        )
        if row_growth > 0:
            return _failure_result(plan, fact_rows, diagnostics, message)

        next_frame = next_frame.drop(
            columns=left_temp_keys + right_temp_keys + [indicator_name]
        )
        merged = next_frame
        for source_column, merged_column in right_column_names.items():
            lineage[(right_table.table_id, source_column)] = merged_column

    return SafeMergeResult(
        success=True,
        fact_table_id=plan.fact_table_id,
        fact_table=plan.fact_table,
        fact_row_count=fact_rows,
        final_row_count=int(len(merged)),
        merged_frame=merged,
        diagnostics=tuple(diagnostics),
    )
