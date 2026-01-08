import os
import json
import asyncio
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from supabase import create_client, Client
from google import genai
import logging
import sys

# Configuración de Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("AliceManager")

# --- CONFIGURACIÓN ---
load_dotenv()
# Las claves se cargan desde las Variables de Entorno de Railway
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
ALLOWED_USER_IDS = [int(x) for x in os.getenv("ALLOWED_USER_IDS", "").split(",") if x.strip()]

# Validación de Entorno
def validate_env():
    missing = []
    if not TELEGRAM_TOKEN: missing.append("TELEGRAM_TOKEN")
    if not SUPABASE_URL: missing.append("SUPABASE_URL")
    if not SUPABASE_KEY: missing.append("SUPABASE_KEY")
    if not GOOGLE_API_KEY: missing.append("GOOGLE_API_KEY")
    if not ALLOWED_USER_IDS: missing.append("ALLOWED_USER_IDS")
    
    if missing:
        logger.error(f"Faltan variables de entorno: {', '.join(missing)}")
        sys.exit(1)

validate_env()

# Conexiones
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
client = genai.Client(api_key=GOOGLE_API_KEY)

# Configuración del Modelo (Gemini 1.5 Flash para rapidez)

logger.info("👩‍💼 ALICE: Sistema Online (Modo Abierto)...")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ALLOWED_USER_IDS:
        logger.warning(f"Acceso denegado a usuario: {user_id} ({update.effective_user.first_name})")
        return # Ignorar silenciosamente o responder error

    logger.info(f"Comando /start recibido de {update.effective_user.first_name}")
    await update.message.reply_text("Hola. Soy Alice, tu Gerente de Operaciones. ¿Qué investigamos hoy?")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    
    if user_id not in ALLOWED_USER_IDS:
        logger.warning(f"Mensaje ignorado de usuario no autorizado: {user_id} ({user_name})")
        await update.message.reply_text("⛔ Lo siento, no tienes autorización para operar este sistema.")
        return
    
    # 1. CLASIFICACIÓN DE INTENCIÓN (Alice piensa)
    prompt = f"""
    Eres Alice. El usuario {user_name} dice: "{user_text}".
    Analiza: ¿Es una orden de trabajo (investigación, estrategia) o una charla casual?
    
    Responde SOLO un JSON con este formato:
    {{
        "es_orden": true/false,
        "tema": "el tema a investigar o null",
        "respuesta_casual": "tu respuesta si es charla o null"
    }}
    """
    
    try:
        response = client.models.generate_content(
            model='gemini-1.5-flash', contents=prompt
        )
        text_clean = response.text.replace('```json', '').replace('```', '').strip()
        decision = json.loads(text_clean)
        
        # 2. SI ES ORDEN -> ENCOLAR TRABAJO
        if decision.get("es_orden"):
            tema = decision.get("tema")
            logger.info(f"Orden detectada: {tema}")
            await update.message.reply_text(f"✅ Entendido, {user_name}. Le paso el encargo a Marcus: '{tema}'.")
            
            # Crear Proyecto en Supabase
            try:
                project_data = supabase.table('projects').insert({"name": f"Inv: {tema}", "client_name": user_name}).execute()
                project_id = project_data.data[0]['id']
            except Exception as e:
                logger.error(f"Error creando proyecto en Supabase: {e}")
                await update.message.reply_text("Hubo un error registrando el proyecto.")
                return
            
            # Escribir en la Pizarra (Blackboard) para Marcus
            supabase.table('blackboard_state').insert({
                "project_id": project_id,
                "current_stage": "research_needed",
                "agent_assigned": "marcus",
                "status": "pending",
                "memory_payload": {"objetivo": tema, "chat_id": chat_id}
            }).execute()
            
        # 3. SI ES CHARLA -> RESPONDER
        else:
            await update.message.reply_text(decision.get("respuesta_casual", "Entendido."))
            
    except Exception as e:
        logger.error(f"Error en handle_message: {e}")
        await update.message.reply_text("Tuve un error procesando eso. ¿Podrías repetirlo?")

if __name__ == '__main__':
    try:
        app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
        app.add_handler(CommandHandler('start', start))
        app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
        app.run_polling()
    except Exception as e:
        logger.critical(f"Error fatal en Alice Manager: {e}")
