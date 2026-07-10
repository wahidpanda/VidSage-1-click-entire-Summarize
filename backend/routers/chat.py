import json
import asyncio

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.database import get_db, SessionLocal
from backend.models import User, Conversation, Message
from backend.schemas import AskIn
from backend.security import get_current_user
from backend.services import llm, rag

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.get("/{conversation_id}/history")
def history(conversation_id: str, db: Session = Depends(get_db),
            user: User = Depends(get_current_user)):
    convo = _owned(db, user, conversation_id)
    return [
        {"role": m.role, "content": m.content,
         "sources": json.loads(m.sources) if m.sources else []}
        for m in convo.messages
    ]


@router.post("/ask")
async def ask(data: AskIn, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    """Real-time answer stream (Server-Sent Events).

    Event protocol:
      {"type":"sources","sources":[...]}   -> retrieved timestamped excerpts
      {"type":"token","token":"..."}       -> incremental answer text
      {"type":"done"}                      -> stream finished
      {"type":"error","message":"..."}     -> something went wrong
    """
    convo = _owned(db, user, data.conversation_id)
    video = convo.video
    past = [{"role": m.role, "content": m.content} for m in convo.messages]

    try:
        context, sources = await asyncio.to_thread(
            rag.build_context, video.video_id, data.question)
    except Exception:
        raise HTTPException(status_code=500, detail="Couldn't search this video's transcript.")

    messages = rag.answer_messages(video.title, context, past, data.question)
    convo_pk = convo.id

    async def event_stream():
        yield _sse({"type": "sources", "sources": sources})
        answer = ""
        try:
            async for token in llm.stream(messages):
                answer += token
                yield _sse({"type": "token", "token": token})
        except RuntimeError as e:          # missing API key — tell the user plainly
            yield _sse({"type": "error", "message": str(e)})
            return
        except Exception:
            yield _sse({"type": "error",
                        "message": "The model is busy right now. Try again in a few seconds."})
            return

        # persist the exchange after the stream completes
        s = SessionLocal()
        try:
            s.add(Message(conversation_ref=convo_pk, role="user", content=data.question))
            s.add(Message(conversation_ref=convo_pk, role="assistant",
                          content=answer, sources=json.dumps(sources)))
            s.commit()
        finally:
            s.close()
        yield _sse({"type": "done"})

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _owned(db: Session, user: User, conversation_id: str) -> Conversation:
    convo = (db.query(Conversation)
             .filter(Conversation.conversation_id == conversation_id,
                     Conversation.user_id == user.id)
             .first())
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found. Load a video first.")
    return convo
