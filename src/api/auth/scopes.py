class Scope:
    CONVERSATIONS_READ = "conversations:read"
    CONVERSATIONS_WRITE = "conversations:write"
    CHAT = "chat"
    FILES_READ = "files:read"
    FILES_WRITE = "files:write"


# Scope assegnabili a una API key personale. Nessuno scope apre ``/admin/*``:
# una chiave agisce come il suo proprietario solo sugli endpoint che dichiarano
# uno di questi scope (deny-by-default, vedi ``require_chat_scope``).
ALLOWED_USER_SCOPES: tuple[str, ...] = (
    Scope.CHAT,
    Scope.CONVERSATIONS_READ,
    Scope.CONVERSATIONS_WRITE,
    Scope.FILES_READ,
    Scope.FILES_WRITE,
)
