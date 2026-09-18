import sqlite3
import json

db_path = "data/aion.db"
conn = sqlite3.connect(db_path)
c = conn.cursor()

c.execute("SELECT server_slug, oauth_config FROM mcp_server_configs WHERE server_slug='khub'")
row = c.fetchone()
if row:
    name, config_json = row
    config = json.loads(config_json)
    print("Old config:", config)
    
    # Update to the new tunnel
    new_tunnel = "https://provincial-messenger-polar-view.trycloudflare.com"
    config["token_url"] = f"{new_tunnel}/token"
    config["authorization_server"] = f"{new_tunnel}/realms/khub"

#     {
#   "remote_url": "https://provincial-messenger-polar-view.trycloudflare.com/mcp",
#   "provider": "generic",
#   "oauth_display_name": "Khub",
#   "token_url": "https://decades-minutes-dark-cancel.trycloudflare.com/token",
#   "authorization_server": "https://decades-minutes-dark-cancel.trycloudflare.com/realms/khub",
#   "resource": "https://provincial-messenger-polar-view.trycloudflare.com/mcp",
#   "authorization_endpoint": "https://provincial-messenger-polar-view.trycloudflare.com/authorize",
#   "registration_endpoint": "https://provincial-messenger-polar-view.trycloudflare.com/register",
#   "client_id": "khub_backend",
#   "client_id_source": "dynamic_registration",
#   "client_secret": "a8SAf0BcJXL0gMRtBGAu0ekwDpO7wnMo"
# }
    
    new_config_json = json.dumps(config)
    print("New config:", new_config_json)
    
    c.execute("UPDATE mcp_server_configs SET oauth_config=? WHERE server_slug='khub'", (new_config_json,))
    conn.commit()
    print("Database updated successfully.")
else:
    print("khub server not found in mcp_server_configs.")

conn.close()
