import uuid
import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import User, Video, Conversation
from backend.schemas import IngestIn
from backend.security import get_current_user
from backend.services import store, rag
from backend.services.youtube import get_video_id, get_transcript, get_metadata, fmt_time

router = APIRouter(prefix="/api/videos", tags=["videos"])


@router.post("/ingest")
async def ingest(data: IngestIn, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    video_id = get_video_id(data.youtube_url)
    if not video_id:
        raise HTTPException(status_code=400, detail="That doesn't look like a YouTube link. Paste a full video URL.")

    meta = get_metadata(f"https://www.youtube.com/watch?v={video_id}")
    language = "en"

    if not store.store_exists(video_id):
        try:
            segments, language = await asyncio.to_thread(get_transcript, video_id)
            await asyncio.to_thread(store.create_store, video_id, segments)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except Exception:
            raise HTTPException(status_code=500, detail="Couldn't process this video right now. Try another one.")

    video = (db.query(Video)
             .filter(Video.user_id == user.id, Video.video_id == video_id)
             .first())
    if not video:
        video = Video(user_id=user.id, video_id=video_id,
                      url=f"https://www.youtube.com/watch?v={video_id}",
                      title=meta["title"], author=meta["author"],
                      thumbnail=meta["thumbnail"], language=language)
        db.add(video)
        db.commit()
        db.refresh(video)

    convo = Conversation(conversation_id=str(uuid.uuid4()),
                         user_id=user.id, video_ref=video.id)
    db.add(convo)
    db.commit()

    # suggested questions are best-effort — never block ingestion on them
    try:
        questions = await rag.suggested_questions(video_id, video.title)
    except Exception:
        questions = []

    return {
        "conversation_id": convo.conversation_id,
        "video": _video_out(video),
        "suggested_questions": questions,
    }


@router.get("")
def library(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    videos = (db.query(Video).filter(Video.user_id == user.id)
              .order_by(Video.created_at.desc()).all())
    return [_video_out(v) for v in videos]


@router.delete("/{video_ref}")
def delete_video(video_ref: int, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    video = db.query(Video).filter(Video.id == video_ref, Video.user_id == user.id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found.")
    db.delete(video)
    db.commit()
    return {"deleted": True}


@router.get("/{video_ref}/transcript")
def transcript(video_ref: int, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    video = _owned(db, user, video_ref)
    segments = store.load_segments(video.video_id)
    return [{"start": s["start"], "label": fmt_time(s["start"]), "text": s["text"]}
            for s in segments]


@router.post("/{video_ref}/summary")
async def summary(video_ref: int, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    video = _owned(db, user, video_ref)
    if not video.summary:
        try:
            video.summary = await rag.summarize(video.video_id, video.title)
            db.commit()
        except Exception:
            raise HTTPException(status_code=502, detail="The summary service is busy. Try again in a moment.")
    return {"summary": video.summary}


@router.post("/{video_ref}/quiz")
async def quiz(video_ref: int, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    video = _owned(db, user, video_ref)
    try:
        return {"quiz": await rag.make_quiz(video.video_id, video.title)}
    except Exception:
        raise HTTPException(status_code=502, detail="Couldn't build a quiz right now. Try again in a moment.")


@router.post("/{video_ref}/chapters")
async def chapters(video_ref: int, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """Timestamped summary — chapters with clickable start times."""
    video = _owned(db, user, video_ref)
    try:
        return {"chapters": await rag.make_chapters(video.video_id, video.title)}
    except Exception:
        raise HTTPException(status_code=502, detail="Couldn't build the timeline right now. Try again in a moment.")


@router.post("/{video_ref}/flashcards")
async def flashcards(video_ref: int, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    video = _owned(db, user, video_ref)
    try:
        return {"cards": await rag.make_flashcards(video.video_id, video.title)}
    except Exception:
        raise HTTPException(status_code=502, detail="Couldn't build flashcards right now. Try again in a moment.")


def _owned(db: Session, user: User, video_ref: int) -> Video:
    video = db.query(Video).filter(Video.id == video_ref, Video.user_id == user.id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found.")
    return video


def _video_out(v: Video) -> dict:
    return {"id": v.id, "video_id": v.video_id, "url": v.url, "title": v.title,
            "author": v.author, "thumbnail": v.thumbnail, "language": v.language,
            "created_at": v.created_at.isoformat()}
