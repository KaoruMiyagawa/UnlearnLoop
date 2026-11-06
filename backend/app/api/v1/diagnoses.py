"""API router for Agent diagnostic cases, hypothesis inspections, and decision stepping."""

from fastapi import APIRouter, Depends

from app.api.v1.dependencies import get_diagnostic_service
from app.api.v1.schemas import (
    DiagnosticCaseResponse,
    DiagnosticStepRequest,
    DiagnosticStepResponse,
    EvidenceLinkResponse,
    HypothesisResponse,
)
from app.application.diagnostic_service import DiagnosticAppService

router = APIRouter(tags=["diagnoses"])


@router.get(
    "/diagnoses/{case_id}",
    response_model=DiagnosticCaseResponse,
    summary="Get diagnostic case detail",
)
def get_diagnostic_case(
    case_id: str,
    service: DiagnosticAppService = Depends(get_diagnostic_service),
) -> DiagnosticCaseResponse:
    """Retrieve diagnostic case state, candidate hypotheses, uncertainty levels, and token consumption."""
    return service.get_diagnostic_case(case_id)


@router.get(
    "/diagnoses/{case_id}/hypotheses",
    response_model=list[HypothesisResponse],
    summary="List candidate error hypotheses",
)
def get_hypotheses(
    case_id: str,
    service: DiagnosticAppService = Depends(get_diagnostic_service),
) -> list[HypothesisResponse]:
    """Retrieve all competing candidate error hypotheses tracked for a diagnostic case."""
    return service.get_hypotheses_for_case(case_id)


@router.get(
    "/diagnoses/{case_id}/evidence",
    response_model=list[EvidenceLinkResponse],
    summary="List evidence links",
)
def get_evidence(
    case_id: str,
    service: DiagnosticAppService = Depends(get_diagnostic_service),
) -> list[EvidenceLinkResponse]:
    """Retrieve supporting and contradicting evidence linked to hypotheses."""
    return service.get_evidence_for_case(case_id)


@router.post(
    "/diagnoses/{case_id}/step",
    response_model=DiagnosticStepResponse,
    summary="Execute Agent diagnostic decision step",
)
def execute_diagnostic_step(
    case_id: str,
    payload: DiagnosticStepRequest | None = None,
    service: DiagnosticAppService = Depends(get_diagnostic_service),
) -> DiagnosticStepResponse:
    """Trigger the DiagnosticAgentEngine to update hypotheses, choose discriminating actions, or assign interventions."""
    idempotency_key = payload.idempotency_key if payload else None
    return service.run_step(case_id, idempotency_key=idempotency_key)


@router.post(
    "/diagnoses/{case_id}/retry",
    response_model=DiagnosticStepResponse,
    summary="Retry diagnostic step",
)
def retry_diagnostic_step(
    case_id: str,
    payload: DiagnosticStepRequest | None = None,
    service: DiagnosticAppService = Depends(get_diagnostic_service),
) -> DiagnosticStepResponse:
    """Retry a diagnostic case currently paused or in retry_waiting state after a transient failure."""
    idempotency_key = payload.idempotency_key if payload else None
    return service.retry_step(case_id, idempotency_key=idempotency_key)
