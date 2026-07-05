from pydantic import BaseModel


class WidgetChatRequest(BaseModel):
    query: str
    visitor_id: str
    conversation_id: str | None = None


class FeedbackRequest(BaseModel):
    message_id: str
    rating: str          # "positive" / "negative"
    visitor_id: str


class LeadRequest(BaseModel):
    visitor_id: str
    conversation_id: str | None = None
    contact_type: str     # "phone" / "wechat"
    contact_value: str
    question: str | None = None