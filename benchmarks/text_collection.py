"""Contrato y contenido editorial del corpus sintético español (#49)."""

FIELDS = ("id", "url", "contenido", "categoria", "tema")
SIZES = (1_000, 10_000, 100_000)
VERSION = 1

# Categoría, tema, consulta específica de tres palabras, descripción editorial.
TOPICS = (
    ("economía", "inflacion", "inflación precios alimentos",
     "Los precios de los alimentos aumentan y la inflación reduce el presupuesto familiar."),
    ("economía", "banca", "banca digital pagos",
     "La banca digital desarrolla pagos seguros y servicios financieros para pequeñas empresas."),
    ("tecnología", "robotica", "robótica automatización industrial",
     "La robótica impulsa la automatización industrial con sensores y nuevos sistemas de control."),
    ("tecnología", "seguridad", "seguridad informática redes",
     "La seguridad informática protege redes y datos personales frente a ataques digitales."),
    ("ambiente", "solar", "energía solar renovable",
     "La energía solar renovable abastece hogares mediante paneles y reduce emisiones contaminantes."),
    ("ambiente", "bosques", "bosques conservación biodiversidad",
     "Los bosques requieren conservación para proteger la biodiversidad y recuperar especies nativas."),
    ("salud", "vacunas", "vacunas prevención enfermedades",
     "Las vacunas facilitan la prevención de enfermedades mediante campañas en centros sanitarios."),
    ("salud", "nutricion", "nutrición alimentación infantil",
     "La nutrición mejora la alimentación infantil con productos frescos y seguimiento médico."),
    ("educación", "escuelas", "escuelas aprendizaje rural",
     "Las escuelas amplían el aprendizaje rural con bibliotecas y capacitación de docentes."),
    ("educación", "universidad", "universidad investigación científica",
     "La universidad promueve investigación científica mediante laboratorios y becas de formación."),
    ("deportes", "futbol", "fútbol campeonato nacional",
     "El fútbol celebra el campeonato nacional con nuevos equipos y sesiones de entrenamiento."),
    ("deportes", "atletismo", "atletismo competencia maratón",
     "El atletismo prepara una competencia de maratón con corredores de distintas regiones."),
)

CONTEXT = (
    "El equipo presentó sus resultados durante una reunión abierta al público.",
    "Las autoridades anunciaron una evaluación independiente para el próximo trimestre.",
    "La asociación local solicitó ampliar el programa hacia otras comunidades.",
    "El informe incluye entrevistas, cifras preliminares y opiniones de especialistas.",
    "Los participantes debatieron las dificultades de financiamiento y organización.",
    "Una portavoz explicó: «Necesitamos continuidad y participación ciudadana».",
)
