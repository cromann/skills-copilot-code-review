"""
Announcement Management API Router

Provides endpoints for creating, reading, updating, and deleting announcements.
Only authenticated users can manage announcements.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from bson import ObjectId
from bson.errors import InvalidId
import logging
from ..database import announcements_collection, teachers_collection

# Configure logging
logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/announcements",
    tags=["announcements"]
)


class AnnouncementCreate(BaseModel):
    """Model for creating a new announcement"""
    message: str = Field(..., min_length=1, max_length=500)
    start_date: Optional[str] = None
    expiration_date: str
    created_by: str


class AnnouncementUpdate(BaseModel):
    """Model for updating an announcement"""
    message: Optional[str] = Field(None, min_length=1, max_length=500)
    start_date: Optional[str] = None
    expiration_date: Optional[str] = None


@router.get("/active")
async def get_active_announcements():
    """
    Get all active announcements (within date range).
    This endpoint is public and does not require authentication.
    """
    try:
        current_date = datetime.now().date().isoformat()
        
        # Find announcements that are currently active
        announcements = list(announcements_collection.find())
        
        active_announcements = []
        for announcement in announcements:
            # Convert _id to string for JSON serialization
            announcement['id'] = str(announcement['_id'])
            del announcement['_id']
            
            # Check if announcement is active
            start_date = announcement.get('start_date')
            expiration_date = announcement.get('expiration_date')
            
            # If start_date is not set or is in the past, and expiration_date is in the future
            is_started = not start_date or start_date <= current_date
            is_not_expired = expiration_date and expiration_date >= current_date
            
            if is_started and is_not_expired:
                active_announcements.append(announcement)
        
        return active_announcements
    except Exception as e:
        # Log error but don't expose details to client
        logger.error(f"Error fetching active announcements: {e}")
        return []


@router.get("/all")
async def get_all_announcements(username: str = Query(...)):
    """
    Get all announcements (for management interface).
    Requires authentication.
    """
    try:
        # Verify user is authenticated
        user = teachers_collection.find_one({"_id": username})
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        
        # Get all announcements
        announcements = list(announcements_collection.find())
        
        # Convert _id to string for JSON serialization
        for announcement in announcements:
            announcement['id'] = str(announcement['_id'])
            del announcement['_id']
        
        # Sort by creation date (newest first)
        announcements.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        
        return announcements
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching all announcements: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch announcements")


@router.post("/")
async def create_announcement(announcement: AnnouncementCreate):
    """
    Create a new announcement.
    Requires authentication.
    """
    try:
        # Verify user is authenticated
        user = teachers_collection.find_one({"_id": announcement.created_by})
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        
        # Validate dates
        try:
            expiration_date = datetime.fromisoformat(announcement.expiration_date).date()
            if announcement.start_date:
                start_date = datetime.fromisoformat(announcement.start_date).date()
                if start_date > expiration_date:
                    raise HTTPException(
                        status_code=400,
                        detail="Start date must be before expiration date"
                    )
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format")
        
        # Create announcement document
        announcement_doc = {
            "message": announcement.message,
            "start_date": announcement.start_date,
            "expiration_date": announcement.expiration_date,
            "created_by": announcement.created_by,
            "created_at": datetime.now().isoformat()
        }
        
        # Insert into database
        result = announcements_collection.insert_one(announcement_doc)
        
        # Return created announcement
        announcement_doc['id'] = str(result.inserted_id)
        del announcement_doc['_id']
        
        return announcement_doc
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating announcement: {e}")
        raise HTTPException(status_code=500, detail="Failed to create announcement")


@router.put("/{announcement_id}")
async def update_announcement(
    announcement_id: str,
    announcement: AnnouncementUpdate,
    username: str = Query(...)
):
    """
    Update an existing announcement.
    Requires authentication.
    """
    try:
        # Verify user is authenticated
        user = teachers_collection.find_one({"_id": username})
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        
        # Find announcement
        try:
            obj_id = ObjectId(announcement_id)
        except InvalidId:
            raise HTTPException(status_code=400, detail="Invalid announcement ID")
        
        existing = announcements_collection.find_one({"_id": obj_id})
        if not existing:
            raise HTTPException(status_code=404, detail="Announcement not found")
        
        # Build update document
        update_doc = {}
        if announcement.message is not None:
            update_doc["message"] = announcement.message
        if announcement.start_date is not None:
            update_doc["start_date"] = announcement.start_date
        if announcement.expiration_date is not None:
            update_doc["expiration_date"] = announcement.expiration_date
        
        # Validate dates using effective post-update values
        try:
            existing_start_str = existing.get("start_date")
            existing_exp_str = existing.get("expiration_date")

            # Determine what the dates will be after this update
            new_start_str = update_doc.get("start_date", existing_start_str)
            new_exp_str = update_doc.get("expiration_date", existing_exp_str)

            new_start = None
            if new_start_str:
                new_start = datetime.fromisoformat(new_start_str).date()

            new_exp = None
            if new_exp_str:
                new_exp = datetime.fromisoformat(new_exp_str).date()

            # Enforce that start date is not after expiration date when both are present
            if new_start and new_exp and new_start > new_exp:
                raise HTTPException(
                    status_code=400,
                    detail="Start date must be before expiration date"
                )
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format")
        
        # Update announcement
        announcements_collection.update_one(
            {"_id": obj_id},
            {"$set": update_doc}
        )
        
        # Return updated announcement
        updated = announcements_collection.find_one({"_id": obj_id})
        updated['id'] = str(updated['_id'])
        del updated['_id']
        
        return updated
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating announcement: {e}")
        raise HTTPException(status_code=500, detail="Failed to update announcement")


@router.delete("/{announcement_id}")
async def delete_announcement(
    announcement_id: str,
    username: str = Query(...)
):
    """
    Delete an announcement.
    Requires authentication.
    """
    try:
        # Verify user is authenticated
        user = teachers_collection.find_one({"_id": username})
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        
        # Delete announcement
        try:
            obj_id = ObjectId(announcement_id)
        except InvalidId:
            raise HTTPException(status_code=400, detail="Invalid announcement ID")
        
        result = announcements_collection.delete_one({"_id": obj_id})
        
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Announcement not found")
        
        return {"message": "Announcement deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting announcement: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete announcement")
