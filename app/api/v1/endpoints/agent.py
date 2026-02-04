from fastapi import APIRouter, Depends, HTTPException
from app.schemas.agent import ChatRequest, ChatResponse
from app.services.agent_service import AgentService

router = APIRouter()

async def get_agent_service():
    return AgentService()

@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    agent_service: AgentService = Depends(get_agent_service)
):
    try:
        response = await agent_service.chat(
            query=request.query,
            session_id=request.session_id,
            story_id=request.story_id
        )
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
