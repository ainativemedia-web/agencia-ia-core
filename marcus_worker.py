import os
import time
import json
from supabase import create_client, Client
from google import genai
from dotenv import load_dotenv
import logging
import sys

# Configuración de Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("MarcusWorker")

# --- CONFIGURACIÓN ---
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# Validación de Entorno
def validate_env():
    missing = []
    if not SUPABASE_URL: missing.append("SUPABASE_URL")
    if not SUPABASE_KEY: missing.append("SUPABASE_KEY")
    if not GOOGLE_API_KEY: missing.append("GOOGLE_API_KEY")
    
    if missing:
        logger.error(f"Faltan variables de entorno: {', '.join(missing)}")
        sys.exit(1)

validate_env()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai_client = genai.Client(api_key=GOOGLE_API_KEY)

logger.info("🕵️ MARCUS: Vigilando la pizarra...")

def check_and_work():
    try:
        # 1. BUSCAR TAREAS PENDIENTES
        response = supabase.table('blackboard_state').select("*")\
            .eq('current_stage', 'research_needed')\
            .eq('status', 'pending')\
            .execute()
        
        tasks = response.data
        
        if tasks:
            for task in tasks:
                process_task(task)
        else:
            logger.debug("💤 Nada por hacer...")
            
    except Exception as e:
        logger.error(f"Error de conexión en loop principal: {e}")

def process_task(task):
    logger.info(f"🚀 Procesando tarea: {task['id']}")
    
    # A. Marcar como 'En Proceso'
    supabase.table('blackboard_state').update({'status': 'processing'}).eq('id', task['id']).execute()
    
    payload = task['memory_payload']
    objetivo = payload.get('objetivo')
    
    # B. INVESTIGACIÓN (Simulada con Gemini Pro)
    prompt = f"""
    Actúa como Marcus, investigador senior.
    Objetivo: {objetivo}
    
    Investiga y genera un reporte estratégico breve con:
    1. Contexto del mercado.
    2. 3 Puntos clave.
    3. Recomendación estratégica.
    
    Responde en formato JSON.
    """
    
    try:
        ai_response = genai_client.models.generate_content(
            model='gemini-1.5-pro-002', contents=prompt
        )
        reporte = ai_response.text
        
        # C. GUARDAR RESULTADO Y CERRAR
        payload['reporte_marcus'] = reporte
        
        # Actualizamos la pizarra: Tarea completada
        supabase.table('blackboard_state').update({
            'status': 'completed',
            'current_stage': 'strategy_ready', # Listo para el siguiente agente
            'memory_payload': payload
        }).eq('id', task['id']).execute()
        
        logger.info(f"✅ Tarea {task['id']} finalizada.")
        
    except Exception as e:
        logger.error(f"Error en investigación de tarea {task['id']}: {e}")
        try:
            supabase.table('blackboard_state').update({'status': 'error'}).eq('id', task['id']).execute()
        except Exception as db_error:
            logger.critical(f"Error fatal actualizando estado de error en DB: {db_error}")

if __name__ == "__main__":
    while True:
        try:
            check_and_work()
        except Exception as e:
            logger.critical(f"Error no manejado en loop de Marcus: {e}")
        time.sleep(10) # Descansa 10 segundos antes de volver a mirar
