import pandas as pd
import os

# Definiamo i dati per il primo foglio: Clienti
df_clienti = pd.DataFrame(
    {
        "client_id": [101, 102, 103, 104],
        "nome": ["Mario Rossi", "Luigi Bianchi", "Anna Verdi", "Giulia Neri"],
        "città": ["Milano", "Roma", "Torino", "Napoli"],
        "email": [
            "mario@example.com",
            "luigi@example.com",
            "anna@example.com",
            "giulia@example.com",
        ],
        "categoria": ["Premium", "Base", "Premium", "Base"],
    }
)

# Definiamo i dati per il secondo foglio: Ordini
df_ordini = pd.DataFrame(
    {
        "ordine_id": [5001, 5002, 5003, 5004, 5005],
        "client_id": [101, 101, 103, 102, 104],
        "data": ["2026-01-10", "2026-01-15", "2026-02-01", "2026-02-05", "2026-02-10"],
        "importo": [250.50, 120.00, 450.00, 85.00, 310.20],
        "stato": [
            "Consegnato",
            "In elaborazione",
            "Consegnato",
            "Spedito",
            "In elaborazione",
        ],
    }
)

# Percorso del file
output_path = "test_agent_db_multi.xlsx"

# Scrittura del file Excel con fogli multipli
with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
    df_clienti.to_excel(writer, sheet_name="Clienti", index=False)
    df_ordini.to_excel(writer, sheet_name="Ordini", index=False)

print(f"File Excel generato correttamente: {os.path.abspath(output_path)}")
