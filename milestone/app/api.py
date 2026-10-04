from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.core import (
    ApprovalUpdate,
    ResearchAssistant,
    ResearchResponse,
)


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResearchRequest(APIModel):
    query: str = Field(min_length=3)
    thread_id: str = Field(default_factory=lambda: f"api-{uuid4()}")


class ApprovalRequestBody(APIModel):
    decision: str = Field(pattern=r"^(PASS|FAIL)$")


class ApprovalFileResponse(APIModel):
    decision: str
    approval_queue: str
    queue_depth: int


class HealthResponse(APIModel):
    status: str
    graph_nodes: list[str]
    approval_queue: str
    queue_depth: int


def create_app(
    workspace_root: Path | str | None = None,
    assistant: ResearchAssistant | None = None,
) -> FastAPI:
    load_dotenv()
    root = Path(workspace_root or Path(__file__).parents[1]).resolve()
    research_assistant = assistant or ResearchAssistant(
        workspace_root=root,
        approval_path=root / "artifacts" / "approval_queue.json",
        log_path=root / "artifacts" / "milestone4.jsonl",
    )

    application = FastAPI(
        title="Milestone 4 Multi-Agent Research API",
        version="1.0.0",
        description=(
            "Supervisor-led research, validated Text-to-SQL, persistent memory, "
            "report writing, and a queue-based human approval flow."
        ),
    )
    application.state.research_assistant = research_assistant

    @application.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            graph_nodes=[
                "supervisor",
                "researcher",
                "writer",
                "approval",
                "finalize",
                "reject",
            ],
            approval_queue=str(research_assistant.approval_queue_path),
            queue_depth=research_assistant.approval_gate.pending_count(),
        )

    @application.post("/approval", response_model=ApprovalFileResponse)
    def update_approval(body: ApprovalRequestBody) -> ApprovalFileResponse:
        update = ApprovalUpdate(decision=body.decision)
        research_assistant.approval_gate.enqueue_decision(update, source="api")
        return ApprovalFileResponse(
            decision=update.decision,
            approval_queue=str(research_assistant.approval_queue_path),
            queue_depth=research_assistant.approval_gate.pending_count(),
        )

    @application.post("/research", response_model=ResearchResponse)
    def research(request: ResearchRequest) -> ResearchResponse:
        try:
            return research_assistant.run(
                query=request.query,
                thread_id=request.thread_id,
            )
        except (OSError, ValueError, RuntimeError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @application.post("/research/stream")
    def research_stream(request: ResearchRequest) -> StreamingResponse:
        def event_source() -> Iterator[str]:
            try:
                for event in research_assistant.stream(
                    query=request.query,
                    thread_id=request.thread_id,
                ):
                    yield (
                        f"event: {event.event}\n"
                        f"data: {event.model_dump_json()}\n\n"
                    )
            except (OSError, ValueError, RuntimeError) as error:
                yield f"event: error\ndata: {str(error)}\n\n"

        return StreamingResponse(
            event_source(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    return application


app = create_app()