from pydantic import BaseModel


class ChatRequest(BaseModel):
    query: str
    conversation_id: str | None = None
    image: str | None = None  # base64 encoded image


class ChatResponse(BaseModel):
    answer: str
    thinking: list[dict] = []
    sources: list[dict] = []
    trace: list[dict] = []
    conversation_id: str = ""


class ConversationCreate(BaseModel):
    title: str = "新对话"


class ConversationOut(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str


class DocumentOut(BaseModel):
    id: str
    filename: str
    size: int
    status: str
    chunk_count: int = 0
    created_at: str

class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: str
    username: str