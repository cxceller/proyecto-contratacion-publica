"""Genera el documento "ANEXO 1 - ESPECIFICACIONES TECNICAS PARA LOS
PROCESOS DE BIENES" de la M.I. Municipalidad de Guayaquil, replicando el
formato exacto de un modelo Word de referencia
(docs/Especificaciones_tecnicas_modelo.docx, documento completo):

- Encabezado y pie de pagina institucionales fijos (banner con el logo y
  la barra tricolor decorativa, y la barra de contacto), como imagenes
  ancladas -- no editables por el usuario.
- Caja de titulo (4 lineas, Arial 13 negrita, centrada): "ANEXO 1",
  "ESPECIFICACIONES TECNICAS PARA LOS PROCESOS DE BIENES" y la
  coordinacion responsable son fijos; solo el "Objeto de contratacion"
  (ultima linea, resaltada en amarillo) es variable.
- Tabla principal de items: por cada item se repite un bloque
  (encabezado de 8 columnas, fila de datos, fila divisora "PARAMETROS /
  ESPECIFICACIONES TECNICAS", fila de especificaciones tecnicas -- cuyo
  contenido depende de si ESE item puntual es un Bien o un Servicio -- y
  una fila vacia de separacion), igual que el modelo real.
- Seccion de condiciones legales/administrativas: mezcla de campos que
  ingresa el usuario y de texto/tablas fijas institucionales, copiadas
  literal del modelo real (marco legal, definiciones, metodologias,
  listas de obligaciones y garantias) -- ver las constantes TEXTO_*/
  TABLA_*_FIJA mas abajo. Termina con la tabla de Firmas de
  Responsabilidad (Elaborado por/Revisado por/Aprobado por).
"""
import base64
import copy
import re
import tempfile
from pathlib import Path

from bs4 import BeautifulSoup
from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_COLOR_INDEX
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Length, Pt
from htmldocx import HtmlToDocx

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
IMAGEN_ENCABEZADO = ASSETS_DIR / "mimg_header.jpg"
IMAGEN_PIE_PAGINA = ASSETS_DIR / "mimg_footer.jpg"

FUENTE = "Arial"
TAMANO_TITULO_PT = 13
TAMANO_ENCABEZADO_TABLA_PT = 9
TAMANO_DATOS_TABLA_PT = 8
TAMANO_DIVISOR_PT = 10
TAMANO_SUBTITULO_PT = 9
TAMANO_PARAMETRO_PT = 9
TAMANO_LEGAL_PT = 10
# Tamano de los 2 unicos titulos de seccion de ancho completo que existen
# de verdad en el modelo real ("REQUERIMIENTOS ADICIONALES OBLIGATORIOS" y
# "PARAMETROS DE EVALUACION Y CALIFICACION") -- todo lo demas que antes se
# dibujaba como "titulo" es en realidad una fila de campo (etiqueta +
# valor) de 2 columnas, confirmado contra el .docx de referencia.
TAMANO_TITULO_SECCION_ANCHA_PT = 14

COLOR_FONDO_ENCABEZADO = "F2F2F2"
# Bordes de la tabla principal de items, replicados del modelo real: azul
# marino institucional, mas gruesos en el contorno exterior que entre
# filas/columnas.
COLOR_BORDE_TABLA_ITEMS = "002060"
GROSOR_BORDE_EXTERIOR = "12"
GROSOR_BORDE_INTERIOR = "8"
# Bordes de la subtabla de parametros (dentro de la celda de
# especificaciones tecnicas de un item Bien): gris claro y mas fino que
# los de la tabla principal, tal como en el modelo.
COLOR_BORDE_TABLA_PARAMETROS = "C0C0C0"
GROSOR_BORDE_TABLA_PARAMETROS = "6"

# Lineas fijas de la caja de titulo (solo "objeto_contratacion" es
# variable -- ver generar_anexo1).
TITULO_ANEXO_FIJO = "ANEXO 1"
TITULO_PROCESO_FIJO = "ESPECIFICACIONES TÉCNICAS PARA LOS PROCESOS DE BIENES"
COORDINACION_FIJA = "COORDINACION DE OBRAS ELÉCTRICAS, TELECOMUNICACIONES Y MANTENIMIENTO DE TÚNELES"

# Medidas replicadas del modelo real (tblW/tblInd/gridCol en twips,
# convertidos aqui a cm -- 1 twip = 1/1440 in, 1 in = 2.54 cm).
_TWIPS_A_CM = 2.54 / 1440
ANCHO_TABLA_CM = 11761 * _TWIPS_A_CM
INDENTACION_TABLA_CM = -1568 * _TWIPS_A_CM
ANCHOS_COLUMNAS_CM = [
    1979 * _TWIPS_A_CM,  # ITEM
    1896 * _TWIPS_A_CM,  # DESCRIPCION
    1161 * _TWIPS_A_CM,  # Unidad de Medida
    1432 * _TWIPS_A_CM,  # CANTIDAD SOLICITADA
    1160 * _TWIPS_A_CM,  # VALOR UNITARIO
    963 * _TWIPS_A_CM,   # VALOR TOTAL
    1751 * _TWIPS_A_CM,  # Descripcion del CPC
    1276 * _TWIPS_A_CM,  # NUMERO CPC
]
ENCABEZADOS_COLUMNAS = [
    "ITEM",
    "DESCRIPCIÓN",
    "Unidad de Medida",
    "Cantidad Solicitada",
    "Valor Unitario",
    "Valor Total",
    "Descripción del CPC",
    "NÚMERO DE CPC",
]
ALINEACIONES_COLUMNAS = [
    WD_ALIGN_PARAGRAPH.CENTER,
    WD_ALIGN_PARAGRAPH.JUSTIFY,
    WD_ALIGN_PARAGRAPH.CENTER,
    WD_ALIGN_PARAGRAPH.CENTER,
    WD_ALIGN_PARAGRAPH.CENTER,
    WD_ALIGN_PARAGRAPH.CENTER,
    WD_ALIGN_PARAGRAPH.JUSTIFY,
    WD_ALIGN_PARAGRAPH.CENTER,
]

# --- Bloques de texto/tabla fijos, copiados literal del modelo real
# (clausulas genericas de la LOSNCP/RGLOSNCP, reutilizables tal cual en
# cualquier Anexo 1, a diferencia de los datos propios de UN contrato
# puntual, que son los campos variables del formulario). ---

TEXTO_MULTAS = (
    "Se impondrá la multa del uno por mil (1 por 1000) por retardo en la ejecución de las "
    "obligaciones contractuales, conforme lo establecido en el contrato, pliego y "
    "ESPECIFICACIONES TÉCNICAS, así como por incumplimientos de las demás obligaciones "
    "contractuales.\n"
    "Estas multas se calcularán por cada día de retardo, sobre la valoración de la obligación "
    "incumplida, conforme lo establecido en el numeral 4 del artículo 82 de la Ley Orgánica del "
    "Sistema Nacional de Contratación Pública, en concordancia con el artículo 375 de su "
    "Reglamento General de aplicación, excepto si media caso fortuito o fuerza mayor, conforme a "
    "lo dispuesto en el artículo 30 de la codificación del Código Civil, debidamente comprobado y "
    "aceptado por la contratante; para lo cual, la contratista notificará al administrador del "
    "contrato dentro de las 48 horas subsiguientes de ocurrido los hechos, transcurrido lo cual, "
    "de no mediar dicha notificación se entenderán como no ocurridos los hechos, que alegue el "
    "contratista como causa para no prestar los servicios a los cuales está obligado y se le "
    "impondrá la multa prevista anteriormente.\n"
    "Si el valor de las multas llegare a superar el valor del 5% del monto total del contrato, la "
    "contratante podrá declarar anticipada y unilateralmente la terminación de este conforme al "
    "numeral 3 del artículo 108 de la LOSNCP.\n"
    "La entidad contratante queda autorizada por la contratista para que haga efectiva la multa "
    "impuesta, de los valores que por la ejecución contractual le corresponde recibir.\n"
    "El administrador del contrato definirá el porcentaje de las obligaciones pendientes de "
    "ejecutar y deberá observar el procedimiento para la imposición de las mismas previsto en el "
    "artículo 376 del RGLOSNCP."
)

TEXTO_GARANTIA_FIEL_CUMPLIMIENTO = (
    "GARANTÍA DE FIEL CUMPLIMIENTO.\n"
    "Previamente a la suscripción del contrato, la contratista deberá entregar la garantía de "
    "fiel cumplimiento del contrato por un valor igual al cinco por ciento (5%) del monto total "
    "del mismo, en una de las formas establecidas en el artículo 85 de la Ley Orgánica del "
    "Sistema Nacional de Contratación Pública.\n"
    "La contratista tiene la obligación de mantener vigente la garantía de fiel cumplimiento "
    "hasta la firma del acta de entrega y recepción definitiva. La devolución de la garantía se "
    "sujetará a lo establecido en el artículo 89 de la Ley Orgánica del Sistema Nacional de "
    "Contratación Pública."
)

TEXTO_GARANTIA_BUEN_USO_ANTICIPO = (
    "GARANTÍA DE BUEN USO DE ANTICIPO\n"
    "Se rendirá por igual valor del anticipo previsto en el presente pliego, que se reducirán en "
    "la proporción que determine el Reglamento, y que respalde el 100% del monto a recibir por "
    "este concepto, la que deberá ser presentada previo la entrega del mismo.\n"
    "El valor será depositado en una cuenta que el contratista aperture en un banco estatal o "
    "privado, en el que el Estado tenga participación accionaria o de capital superior al "
    "cincuenta por ciento. El contratista, en forma previa a la suscripción del contrato, deberá "
    "presentar un certificado de la institución bancaria o financiera en la que tenga a su "
    "disposición una cuenta en la cual serán depositados los valores correspondientes al "
    "anticipo, de haber sido concedido.\n"
    "El contratista deberá autorizar expresamente en el contrato el levantamiento del sigilo "
    "bancario de la cuenta en la que será depositado el anticipo recibido. El Administrador del "
    "Contrato designado por la entidad contratante verificará que los movimientos de la cuenta "
    "correspondan estrictamente al procedimiento de devengamiento del anticipo o ejecución "
    "contractual.\n"
    "El oferente o adjudicatario podrá renunciar expresamente al uso y otorgamiento del "
    "anticipo, en cuyo caso no deberá rendir la garantía correspondiente."
)

TEXTO_GARANTIA_RESPONSABILIDAD_CIVIL_PLANTILLA = (
    "GARANTÍA DE RESPONSABILIDAD CIVIL\n"
    'Al momento de suscribir el contrato de "{objeto}", la contratista deberá justificar que '
    "cuenta con una póliza de responsabilidad civil contra daños a terceros y/o usuarios, para "
    "garantizar a quienes puedan resultar perjudicados en el proceso, con un valor asegurado "
    "mínimo de USD {monto} por evento.\n"
    "La póliza deberá permanecer vigente durante todo el plazo de ejecución del contrato y "
    "hasta su recepción definitiva.\n"
    "La garantía deberá cubrir los siguientes escenarios:\n"
    "Daños a terceros ocasionados por maniobras de montaje, desmontaje, izaje o traslado de "
    "equipos (incluyendo el uso de camiones grúa-canasta, andamios u otros medios de acceso), "
    "así como por una señalización insuficiente o inadecuada de las áreas de trabajo dentro o en "
    "los accesos a los túneles.\n"
    "Daños a terceros o usuarios derivados del desprendimiento, caída o falla de los letreros, "
    "gabinetes o de sus componentes ya instalados, o de sus estructuras y elementos de sujeción, "
    "ocurridos durante la ejecución del contrato.\n"
    "Daños a terceros o a la infraestructura durante la ejecución de los trabajos de "
    "mantenimiento preventivo sobre los letreros de mensajes variables (VMS), los letreros de "
    "control de carril (LCS), las barreras vehiculares y los semáforos."
)

TEXTO_VIGENCIA_OFERTA_PLANTILLA = (
    "La oferta estará vigente por {dias} días, contados a partir de la presentación de esta, o "
    "de conformidad a lo dispuesto en el artículo 29 de la Ley Orgánica del Sistema Nacional de "
    "Contratación Pública."
)

TEXTO_REAJUSTE_PRECIOS = (
    "El valor de la presente contratación no se sujeta al sistema de precios unitarios "
    "consecuentemente no habrá lugar al reajuste de precios."
)

TEXTO_ANALISIS_ESTRATEGIA_FIJO = (
    "A efectos de seleccionar el tipo de procedimiento de contratación, la entidad contratante "
    "deberá determinar, al menos:\n"
    "i) Si los bienes o servicios son estandarizados y de adquisición frecuente; (Análisis de "
    "procesos de la entidad iguales o similares y análisis de sus características técnicas, si el "
    "precio más bajo fue el único parámetro de evaluación o existieron más, en los últimos 2 "
    "años).\n"
    "ii) Si existe un mercado competitivo de proveedores calificados.\n"
    "iii) Si el precio refleja por sí solo el mejor valor por dinero o si deben priorizarse otros "
    "atributos; identifique la alternativa que permita maximizar los resultados del gasto "
    "público, considerando no solo el precio, sino también otros atributos relevantes como la "
    "calidad, sostenibilidad, innovación, costos del ciclo de vida, desempeño y funcionalidad, "
    "etc.\n"
    "Deberán desarrollarse los Atributos de Evaluación Más Allá del Precio. El análisis deberá "
    "considerar, de manera motivada y proporcional al objeto contractual, los atributos que "
    "apliquen del informe de necesidad y por qué ayudan a maximizar los resultados del gasto "
    "público durante el ciclo de vida del bien, servicio u obra. En caso de que alguno de ellos "
    "sea más relevante que el precio, deberá indicarse y sustentarse; caso contrario, deberá "
    "indicarse que lo que prevalece es el precio.\n"
    "El precio solo no necesariamente representa el mejor valor por dinero, dado que también "
    "podrían priorizarse como parte de la oferta atributos distintos al precio, tales como la "
    "calidad, la sostenibilidad, la innovación, los costos del ciclo de vida, y, en general, "
    "cuando se utilizan criterios de desempeño y funcionales, y no descripciones exactas del bien "
    "y/o servicio o que sean limitantes en la participación de oferentes.\n"
    "Cuando el precio más bajo y el mercado competitivo representen el mejor valor por dinero, se "
    "aplicará Subasta Inversa Electrónica; en caso contrario, Licitación. Para las contrataciones "
    "de obra siempre se optará por el procedimiento de Licitación."
)

TEXTO_ADMINISTRADOR_INTRO_PLANTILLA = (
    "Se recomienda designar como administrador del contrato, a {nombre}, con cédula {cedula}, "
    "en cargo de {cargo}, a la fecha, o quien haga sus veces.\n"
    "Para los efectos deberá cumplir con las siguientes atribuciones:"
)

TEXTO_ATRIBUCIONES_ADMINISTRADOR = [
    "Coordinar todas las acciones necesarias para garantizar la debida ejecución del contrato;",
    "Cumplir y hacer cumplir todas las obligaciones derivadas del contrato y los documentos que "
    "lo componen;",
    "Adoptar las acciones para evitar retrasos injustificados en la ejecución del contrato;",
    "Imponer las multas establecidas en el contrato, para lo cual se deberá respetar el debido "
    "proceso;",
    "Administrar las garantías correspondientes que se mantendrán vigentes de acuerdo a su "
    "naturaleza, esta obligación podrá ser coordinada con el tesorero de la entidad contratante "
    "o quien haga sus veces, a quien corresponde el control y custodia de las garantías. La "
    "responsabilidad por la gestión de las garantías será solidaria entre el administrador del "
    "contrato y el tesorero;",
    "Reportar a la máxima autoridad de la entidad contratante, cualquier aspecto operativo, "
    "técnico, económico y de otra naturaleza que pudieren afectar al cumplimiento del contrato;",
    "Coordinar con las direcciones institucionales y con los profesionales de la entidad "
    "contratante, que, por su competencia, conocimientos y perfil, sea indispensable su "
    "intervención para garantizar la debida ejecución del contrato;",
    "Notificar la disponibilidad del anticipo cuando sea contemplado en el contrato como forma "
    "de pago coordinando con el área financiera de la entidad contratante;",
    "Verificar los movimientos de la cuenta bancaria del contratista, y su relación con el "
    "devengamiento del anticipo o lo correspondiente a la ejecución contractual;",
    "Proporcionar al contratista las instrucciones necesarias para garantizar el cumplimiento "
    "del contrato;",
    "Requerir motivadamente al contratista, la sustitución de cualquier integrante de su "
    "personal cuando lo considere incompetente o negligente en su oficio, presente una conducta "
    "incompatible con sus obligaciones, o se negare a cumplir las estipulaciones del contrato y "
    "los documentos anexos, debidamente justificado. El personal con el que se sustituya deberá "
    "acreditar la misma o mejor capacidad, experiencia y demás exigencias establecidas en los "
    "pliegos;",
    "Autorizar o negar el cambio del personal asignado a la ejecución del contrato, verificando "
    "que el personal que el contratista pretende sustituir acredite la misma o mejor capacidad, "
    "experiencia y demás exigencias establecidas en los pliegos, desarrollando adecuadamente las "
    "funciones encomendadas;",
    "Verificar de acuerdo con la naturaleza del objeto de contratación, que el contratista "
    "disponga de todos los permisos y autorizaciones para el ejercicio de su actividad, en "
    "cumplimiento de la legislación ambiental, seguridad industrial y salud ocupacional, "
    "legislación laboral, y aquellos términos o condiciones adicionales que se hayan "
    "establecidos en el contrato;",
    "Reportar a las autoridades competentes, cuando tenga conocimiento que el contratista se "
    "encuentra incumpliendo sus obligaciones laborales y patronales conforme a la ley;",
    "Verificar permanentemente y en los casos aplicables, el cumplimiento de participación "
    "nacional, desagregación y transferencia tecnológica, así como cualquier otra figura "
    "legalmente exigible y que se encuentre prevista en el contrato o que por la naturaleza del "
    "objeto y el procedimiento de contratación sean imputables al contratista;",
    "Elaborar e intervenir en las actas de entrega recepción a las que hace referencia el "
    "artículo 93 de la Ley Orgánica del Sistema Nacional de Contratación Pública; así como, "
    "coordinar con el contratista la recepción del mismo;",
    "Publicar en el Portal de Contratación Pública durante la fase contractual toda la "
    "información relevante, de conformidad con los manuales de usuario o instructivos que emita "
    "el Servicio Nacional de Contratación Pública. Para dicho efecto, el usuario creador del "
    "proceso deberá habilitar el usuario para el administrador del contrato;",
    "Preparar y organizar el expediente de toda la gestión de administración del contrato, "
    "dejando evidencia documental a efectos de las auditorías ulteriores que los órganos de "
    "control del Estado realicen;",
    "Solicitar a los contratistas y servidores que elaboraron los estudios, que en el término "
    "máximo de quince (15) días, desde la notificación, informen sobre la existencia de "
    "justificación para suscribir contratos complementarios, órdenes de trabajo y diferencias en "
    "cantidades de obra que superen el quince por ciento (15%) del valor del contrato principal;",
    "Informar a la máxima autoridad de la entidad contratante, la modificación de las "
    "características técnicas de los productos a ser entregados, de ser el caso; y,",
    "Cualquier otra que de acuerdo con la naturaleza del objeto de contratación sea "
    "indispensable para garantizar su debida ejecución. Las atribuciones adicionales del "
    "administrador del contrato deberán estar descritas en el contrato.",
]

# Tras las 21 atribuciones numeradas, el modelo agrega -- sin numeracion propia --
# una frase de transicion, un listado de obligaciones adicionales en vinetas, y un
# parrafo de cierre sobre el cambio de administrador. No son continuacion de la
# lista numerada de arriba (serian los items 22-33 si se numeraran, pero el modelo
# real los presenta como vinetas sueltas).
TEXTO_ADMINISTRADOR_OBLIGACIONES_INTRO = (
    "El/la administrador/a del contrato tendrá, a más de las establecidas en la normativa legal "
    "vigente, las siguientes obligaciones y atribuciones, según corresponda:"
)

TEXTO_ADMINISTRADOR_OBLIGACIONES_ADICIONALES = [
    "Realizar un informe motivado y recomendar de manera expresa a la máxima autoridad o su "
    "delegado la autorización o negativa a la solicitud de prórroga efectuada por el "
    "contratista, la suscripción de un contrato modificatorio o complementario, y la suspensión "
    "de la ejecución del contrato por causas imputables a la entidad contratante.",
    "Recomendar a la máxima autoridad o su delegado, mediante informe motivado, la terminación "
    "del contrato por cualquiera de las causales previstas en el mismo o en la Ley Orgánica del "
    "Sistema Nacional de Contratación Pública.",
    "Elaborar e intervenir en las actas de entrega recepción a las que hace referencia el "
    "artículo 93 de la Ley Orgánica del Sistema Nacional de Contratación Pública; así como, "
    "coordinar con el contratista, la recepción del mismo; según lo determina el numeral 13 de "
    "Art. 361 del RGLOSNCP.",
    "Realizar la liquidación económica del contrato.",
    "Solicitar los pagos que se deriven por el cabal cumplimiento del contrato.",
    "Aprobar los productos y servicios que se generen durante la ejecución del contrato.",
    "Contestar dentro del plazo establecido en el contrato cualquier petición o reclamo "
    "formulados por el contratista.",
    "En el caso de terminación de la relación laboral con la Presidencia de la República del "
    "Ecuador, el administrador deberá elaborar el informe del estado actual del contrato a su "
    "cargo y solicitar la designación de un nuevo administrador. Como administrador saliente "
    "tiene la obligación de entregar al jefe inmediato superior todos los documentos originales, "
    "informes, detalle de productos recibidos, con la finalidad de dar continuidad a la "
    "contratación y las obligaciones adquiridas para el cierre y finalización del proceso en el "
    "portal institucional del SERCOP.",
    "Comunicar al contratista los cambios requeridos en la ejecución del contrato.",
    "Las demás obligaciones previstas en la Ley Orgánica del Sistema Nacional de Contratación "
    "Pública, su Reglamento, Resoluciones del Servicio Nacional de Contratación Pública "
    "(SERCOP), las Normas de Control Interno de la Contraloría General del Estado, el contrato "
    "que se suscriba entre las partes y demás normativa aplicable.",
]

TEXTO_ADMINISTRADOR_CIERRE = (
    "La Municipalidad de Guayaquil podrá cambiar al/la administrador/a del contrato, para lo "
    "cual bastará una comunicación escrita al contratista; sin que sea necesaria la "
    "modificación del texto contractual."
)

TEXTO_TIEMPO_EXISTENCIA_LEGAL = (
    "Art. 93.-Reglas de participación.-  1. Tiempo de existencia legal de personas jurídicas: "
    "para procedimientos de contratación cuyo presupuesto referencial sea igual o inferior a "
    "USD$ 500.000,00 (Quinientos mil dólares de los Estados Unidos de América con 00/100), no "
    "habrá tiempo de existencia legal mínima requerida. Para los procedimientos de contratación "
    "que sobrepasen el monto del presupuesto referencial antes mencionado el tiempo de "
    "existencia legal será mínimo de tres (3) años."
)

TEXTO_PATRIMONIO_INTRO = (
    "Art. 93.- Reglas de participación.- 2. Patrimonio de personas jurídicas: en el caso de "
    "personas jurídicas, la entidad contratante verificará que el patrimonio sea igual o superior "
    "a la relación con el presupuesto referencial del procedimiento de contratación.\n"
    "El patrimonio se podrá verificar a través de la declaración del impuesto a la renta del "
    "último ejercicio fiscal realizado ante el Servicio de Rentas Internas, o por el documento "
    "equivalente en el país de origen para aquellas ofertas extranjeras."
)

TABLA_PATRIMONIO_ENCABEZADO = [
    "Fracción básica",
    "Exceso hasta",
    "Patrimonio exigido sobre la fracción básica",
    "Patrimonio exigido sobre el excedente de la fracción básica",
]
TABLA_PATRIMONIO_BIENES_SERVICIOS = [
    ["0", "500.000,00 incluido", "-", "5% sobre el exceso de 250.000 incluido"],
    ["500.000,01", "1'000.000,00 incluido", "15.000,00", "10% sobre el exceso de la fracción básica"],
    ["1'000.000,01", "5'000.000,00 incluido", "75.000,00", "12,5% sobre el exceso de la fracción básica"],
    ["5'000.000,01", "10'000.000,00 incluido", "625.000,00", "15% sobre el exceso de la fracción básica"],
    ["10'000.000,01", "En adelante", "1.500.000,00", "17,5% sobre el exceso de la fracción básica"],
]
TABLA_PATRIMONIO_OBRAS = [
    ["0,00", "200.000,00 incluido", "NO APLICA", "5% sobre el exceso de la fracción básica"],
    ["200.000,01", "500.000,00 incluido", "3.000,00", "5% sobre el exceso de la fracción básica"],
    ["500.000,01", "1'000.000,00 incluido", "15.000,00", "10% sobre el exceso de la fracción básica"],
    ["1'000.000,01", "5'000.000,00 incluido", "75.000,00", "12,5% sobre el exceso de la fracción básica"],
    ["5'000.000,01", "10'000.000,00 incluido", "625.000,00", "15% sobre el exceso de la fracción básica"],
    ["10'000.000,01", "En adelante", "1.500.000,00", "17,5% sobre el exceso de la fracción básica"],
]

TEXTO_EXPERIENCIA_GENERAL_PLANTILLA = (
    "De manera concordante con lo señalado en el informe de necesidad, y en aplicación del "
    "principio de mejor valor por dinero, el oferente deberá acreditar experiencia general en la "
    "ejecución de contratos vinculados al objeto de la presente contratación, ejecutados dentro "
    "de los últimos veinte (20) años previos a la publicación del proceso.\n"
    "Este atributo se encuentra atado a la necesidad institucional, por cuanto garantiza que el "
    "proponente cuente con la capacidad técnica y operativa para responder de manera eficiente a "
    "los requerimientos durante la ejecución del contrato, así como para su pago y liquidación.\n"
    "Monto mínimo de experiencia general requerido: no mayor al {pct_general}% del presupuesto "
    "referencial del presente proceso, que podrá acreditarse en uno o varios contratos.\n"
    "Para acreditar la experiencia general del oferente, se deberá presentar: en el caso de "
    "instituciones del sector público: copia de contratos ejecutados o certificados de "
    "cumplimiento, más acta de entrega recepción ejecutadas. cuando se trate de instituciones del "
    "sector privado: se deberá presentar contrato o certificados de cumplimiento más acta de "
    "entrega recepción ejecutados, más facturas con sus comprobantes de retención (de ser el "
    "caso).\n"
    "Los documentos para acreditar la experiencia deberán, especificar claramente el período de "
    "contratación, detalle del bien o servicio adquirido y su monto de contratación, firma y "
    "cargo de la persona de la institución que emitió el documento."
)

TEXTO_EXPERIENCIA_ESPECIFICA_PLANTILLA = (
    "De manera concordante con lo señalado en el informe de necesidad, y en aplicación del "
    "principio de mejor valor por dinero, el oferente deberá acreditar experiencia específica "
    "directamente relacionada con el objeto de la presente contratación, ejecutados dentro de "
    "los últimos veinte (20) años previos a la publicación del proceso.\n"
    "Este atributo se encuentra atado a la necesidad institucional, por cuanto la contratación "
    "exige que el proponente responda de manera eficiente durante la ejecución del contrato, así "
    "como en su pago y liquidación.\n"
    "Monto mínimo de experiencia específica requerido: no mayor al {pct_especifica}% del "
    "presupuesto referencial del presente proceso, que podrá acreditarse en uno o varios "
    "contratos.\n"
    "Para acreditar la experiencia general del oferente, se deberá presentar: en el caso de "
    "instituciones del sector público: copia de contratos ejecutados o certificados de "
    "cumplimiento, más acta de entrega recepción ejecutadas. cuando se trate de instituciones del "
    "sector privado: se deberá presentar contrato o certificados de cumplimiento más acta de "
    "entrega recepción ejecutados, más facturas con sus comprobantes de retención (de ser el "
    "caso).\n"
    "Los documentos para acreditar la experiencia deberán, especificar claramente el período de "
    "contratación, detalle del bien o servicio adquirido y su monto de contratación, firma y "
    "cargo de la persona de la institución que emitió el documento."
)

TEXTO_FORMACION_PERSONAL_TECNICO_PLANTILLA = (
    "Responsable técnico: Deberá acreditar título de {titulo_profesional}.\n"
    "Notas: Los títulos profesionales del personal técnico deberán estar registrados en el "
    "Senescyt.\n"
    "El personal técnico deberá contar con el certificado de Competencias en Prevención de "
    "Riesgos Laborales o la Certificación en Prevención de Riesgos Laborales, debidamente "
    "avalado por el Ministerio de Trabajo."
)

TEXTO_EXPERIENCIA_PERSONAL_TECNICO = (
    "La definición adecuada del personal técnico requerido constituye un elemento estratégico "
    "para garantizar el principio de mejor valor por dinero, en la medida en que la calidad del "
    "recurso humano incide directamente en la eficiencia, efectividad y alcance de los resultados "
    "esperados.\n"
    "En este contexto, la exigencia del personal técnico mínimo —con experiencia comprobada en "
    "las responsabilidades mínimas que se detallan— permite a la entidad contratante reducir "
    "riesgos de ineficiencia, evitar gastos innecesarios y maximizar el rendimiento de la "
    "inversión pública.\n"
    "Para acreditar la experiencia del personal técnico: en el caso de acreditar experiencia con "
    "entidades del sector público deberá presentar copia de certificados de cumplimiento o copia "
    "de contratos ejecutados, más actas de entrega recepción ejecutado. Si la contratante es del "
    "sector privado, presentará contrato o certificados de cumplimiento o acta de entrega "
    "recepción ejecutadas, más facturas y comprobantes de retención (de ser el caso) o el "
    "historial de tiempo de trabajo por empleador emitido por el IESS con el respectivo código "
    "QR.\n"
    "Los documentos para acreditar la experiencia deberán especificar claramente el período de "
    "contratación, detalle del bien o servicio adquirido, tiempo de ejecución y su monto de "
    "contratación, firma y cargo de la persona de la institución que emitió el documento.\n"
    "Se reconocerá la experiencia adquirida en relación de dependencia, si el certificado emitido "
    "por el contratista demuestra su participación efectiva, como empleado privado, en la "
    "ejecución del o los servicios.\n"
    "Las personas naturales que hayan sido servidores públicos, y que hayan ejercido funciones "
    "como administradores de contrato, fiscalizadores, gerentes, directores técnicos o "
    "similares, no podrán acreditar experiencia general o específica como contratistas.\n"
    "Los títulos profesionales de las personas sometidas a evaluación deberán estar registrados "
    "en el SENESCYT, caso contrario no serán sujetos de evaluación.\n"
    "Se deberá presentar obligatoriamente la hoja de vida del profesional de acuerdo a los "
    "modelos de los formularios con todos los documentos de respaldo."
)

TEXTO_PARAMETROS_EVALUACION_INTRO = (
    "De conformidad con lo dispuesto en el artículo 3 de la Ley Orgánica del Sistema Nacional de "
    "Contratación Pública y el artículo 74 de su Reglamento General, se aplicará el principio de "
    "mejor valor por dinero, entendido como la selección de la oferta que, en su conjunto, "
    "garantice el uso más eficiente, eficaz y económico de los recursos públicos, considerando "
    "no únicamente el precio, sino los atributos técnicos directamente relacionados con el "
    "objeto contractual."
)

TEXTO_CERTIFICADO_PROVEEDOR_EXCLUSIVO_INTRO = (
    "Certificado de proveedor exclusivo o autorizado, en caso de aplicar, conforme a la "
    "normativa vigente del Servicio Nacional de Contratación Pública."
)

TEXTO_CHECKLIST_INTRO = "Aplica para todos los procedimientos."

TEXTO_PUNTAJE_INTRO = (
    "El puntaje puede variar de acuerdo con la Comisión Técnica. Solo las ofertas que cumplan "
    "con los requisitos mínimos serán objeto de evaluación por puntaje. No se otorgará puntaje a "
    "la experiencia general ni a la experiencia específica mínima requerida, por ser de "
    "cumplimiento obligatorio; para que sean susceptibles de calificación por puntaje deberán ser "
    "mayores a lo establecido como requisito mínimo. Se otorgará el máximo puntaje a la o las "
    "ofertas que presenten como experiencia adicional (general o específica) el monto del "
    "presupuesto referencial multiplicado por un factor de 1,25, y a las demás ofertas se "
    "asignará un puntaje directamente proporcional."
)
TABLA_PUNTAJE_ENCABEZADO = ["Criterio", "Puntaje máximo"]
TABLA_PUNTAJE_FIJA = [
    ["Experiencia General", "10"],
    ["Experiencia Específica", "20"],
    ["Experiencia del Personal Técnico", "10"],
    ["Oferta Económica", "50"],
    ["Valor Agregado Ecuatoriano", "10"],
    ["TOTAL", "100"],
]

TABLA_CHECKLIST_ENCABEZADO = ["Parámetro", "Cumple", "No Cumple", "Observaciones"]
TABLA_CHECKLIST_CRITERIOS_FIJOS = [
    "Integridad de la Oferta",
    "Equipo mínimo",
    "Personal técnico mínimo",
    "Experiencia mínima del personal técnico",
    "Especificaciones técnicas / Términos de referencia",
    "Otro(s) parámetro(s) resuelto(s) por la entidad contratante",
]

FIRMA_APROBADO_POR_DEFECTO_NOMBRE = "DR. XAVIER ZAMBRANO ARAGUNDY"
FIRMA_APROBADO_POR_DEFECTO_CARGO = (
    "COORDINADOR GENERAL COORDINACION GENERAL DE OBRAS ELÉCTRICAS, TELECOMUNICACIONES Y "
    "MANTENIMIENTO DE TÚNELES"
)


def _aplicar_fuente(run, tamano_pt: float, negrita: bool = True, resaltado=None, italica: bool = False) -> None:
    run.font.name = FUENTE
    run.font.size = Pt(tamano_pt)
    run.font.bold = negrita
    run.font.italic = italica
    r_fonts = run._element.get_or_add_rPr().get_or_add_rFonts()
    r_fonts.set(qn("w:eastAsia"), FUENTE)
    if resaltado is not None:
        run.font.highlight_color = resaltado


def _sombrear_celda(cell, color_hex: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), color_hex)
    tc_pr.append(shd)


def _bordes_tabla(color: str, grosor_exterior: str, grosor_interior: str):
    """Arma un w:tblBorders con el mismo grosor en los 4 lados exteriores
    y (opcionalmente distinto) en las lineas interiores, tal como se
    definen los bordes de tabla en el modelo Word de referencia."""
    bordes = OxmlElement("w:tblBorders")
    for etiqueta, grosor in (
        ("top", grosor_exterior),
        ("left", grosor_exterior),
        ("bottom", grosor_exterior),
        ("right", grosor_exterior),
        ("insideH", grosor_interior),
        ("insideV", grosor_interior),
    ):
        borde = OxmlElement(f"w:{etiqueta}")
        borde.set(qn("w:val"), "single")
        borde.set(qn("w:sz"), grosor)
        borde.set(qn("w:space"), "0")
        borde.set(qn("w:color"), color)
        bordes.append(borde)
    return bordes


def _aplicar_bordes_tabla_items(tbl_pr) -> None:
    """w:tblBorders con el azul marino institucional del modelo -- debe
    insertarse despues de tblInd y antes de tblLayout/tblCellMar segun el
    orden que exige el esquema CT_TblPrBase, por eso se llama al final de
    _configurar_propiedades_tabla_items en vez de antes."""
    tbl_pr.append(_bordes_tabla(COLOR_BORDE_TABLA_ITEMS, GROSOR_BORDE_EXTERIOR, GROSOR_BORDE_INTERIOR))


def _configurar_propiedades_tabla_items(tabla) -> None:
    tabla.alignment = WD_TABLE_ALIGNMENT.LEFT
    tbl_pr = tabla._tbl.tblPr

    tbl_w = OxmlElement("w:tblW")
    tbl_w.set(qn("w:type"), "dxa")
    tbl_w.set(qn("w:w"), str(Cm(ANCHO_TABLA_CM).twips))
    tbl_pr.append(tbl_w)

    tbl_ind = OxmlElement("w:tblInd")
    tbl_ind.set(qn("w:type"), "dxa")
    tbl_ind.set(qn("w:w"), str(Cm(INDENTACION_TABLA_CM).twips))
    tbl_pr.append(tbl_ind)

    _aplicar_bordes_tabla_items(tbl_pr)


def _fijar_anchos_fila(celdas, anchos: list[Length]) -> None:
    for celda, ancho in zip(celdas, anchos):
        celda.width = ancho
        celda.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER


def _configurar_encabezado_pie(documento: Document) -> None:
    seccion = documento.sections[0]
    seccion.header_distance = Cm(0.3)
    seccion.footer_distance = Cm(1.25)

    parrafo_encabezado = seccion.header.paragraphs[0]
    parrafo_encabezado.alignment = WD_ALIGN_PARAGRAPH.CENTER
    parrafo_encabezado.add_run().add_picture(str(IMAGEN_ENCABEZADO), width=Cm(19))

    parrafo_pie = seccion.footer.paragraphs[0]
    parrafo_pie.alignment = WD_ALIGN_PARAGRAPH.CENTER
    parrafo_pie.add_run().add_picture(str(IMAGEN_PIE_PAGINA), width=Cm(17))


def _agregar_caja_titulo(documento: Document, objeto_contratacion: str) -> None:
    tabla = documento.add_table(rows=4, cols=1)
    tabla.style = "Table Grid"
    tabla.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl_w = OxmlElement("w:tblW")
    tbl_w.set(qn("w:type"), "dxa")
    tbl_w.set(qn("w:w"), str(Cm(ANCHO_TABLA_CM).twips))
    tabla._tbl.tblPr.append(tbl_w)

    textos_fijos = [TITULO_ANEXO_FIJO, TITULO_PROCESO_FIJO, COORDINACION_FIJA]
    for fila, texto in zip(tabla.rows[:3], textos_fijos):
        celda = fila.cells[0]
        celda.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        parrafo = celda.paragraphs[0]
        parrafo.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = parrafo.add_run(texto)
        _aplicar_fuente(run, TAMANO_TITULO_PT)

    celda_libre = tabla.rows[3].cells[0]
    celda_libre.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    parrafo_libre = celda_libre.paragraphs[0]
    parrafo_libre.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_libre = parrafo_libre.add_run(objeto_contratacion or "LLENAR")
    _aplicar_fuente(run_libre, TAMANO_TITULO_PT, resaltado=WD_COLOR_INDEX.YELLOW)


def _agregar_fila_encabezado_item(tabla, anchos: list[Length]) -> None:
    fila = tabla.add_row()
    _fijar_anchos_fila(fila.cells, anchos)
    for celda, texto in zip(fila.cells, ENCABEZADOS_COLUMNAS):
        _sombrear_celda(celda, COLOR_FONDO_ENCABEZADO)
        parrafo = celda.paragraphs[0]
        parrafo.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = parrafo.add_run(texto)
        _aplicar_fuente(run, TAMANO_ENCABEZADO_TABLA_PT)


def _agregar_fila_datos_item(tabla, numero_item: int, item: dict, anchos: list[Length]) -> None:
    fila = tabla.add_row()
    _fijar_anchos_fila(fila.cells, anchos)
    valores = [
        str(numero_item),
        item.get("descripcion", ""),
        item.get("unidad_medida", ""),
        item.get("cantidad_solicitada", ""),
        item.get("valor_unitario", ""),
        item.get("valor_total", ""),
        item.get("descripcion_cpc", ""),
        item.get("numero_cpc", ""),
    ]
    for celda, valor, alineacion in zip(fila.cells, valores, ALINEACIONES_COLUMNAS):
        parrafo = celda.paragraphs[0]
        parrafo.alignment = alineacion
        run = parrafo.add_run(str(valor))
        _aplicar_fuente(run, TAMANO_DATOS_TABLA_PT)


def _agregar_fila_divisor_especificaciones(tabla, anchos: list[Length]) -> None:
    fila = tabla.add_row()
    _fijar_anchos_fila(fila.cells, anchos)
    celda_parametros = fila.cells[0]
    celda_specs = fila.cells[1]
    for celda_extra in fila.cells[2:]:
        celda_specs = celda_specs.merge(celda_extra)

    for celda, texto in ((celda_parametros, "PARÁMETROS"), (celda_specs, "ESPECIFICACIONES TÉCNICAS")):
        celda.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        parrafo = celda.paragraphs[0]
        parrafo.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = parrafo.add_run(texto)
        _aplicar_fuente(run, TAMANO_DIVISOR_PT)


def _agregar_parrafo_campo(
    celda, etiqueta: str, valor: str, primero: bool = False, resaltar_si_vacio: bool = False
) -> None:
    parrafo = celda.paragraphs[0] if primero else celda.add_paragraph()
    run_etiqueta = parrafo.add_run(f"{etiqueta}: ")
    _aplicar_fuente(run_etiqueta, TAMANO_SUBTITULO_PT, negrita=True)
    run_valor = parrafo.add_run(valor or "LLENAR")
    resaltado = WD_COLOR_INDEX.YELLOW if (resaltar_si_vacio and not valor) else None
    _aplicar_fuente(run_valor, TAMANO_SUBTITULO_PT, negrita=False, resaltado=resaltado)


def _agregar_fila_especificaciones_tecnicas(tabla, item: dict, anchos: list[Length]) -> None:
    """Contenido de la celda "ESPECIFICACIONES TECNICAS": distinto segun
    item["tipo"] sea "Bien" (subtitulo resaltado en verde + subtabla de
    parametros nombre/valor) o "Servicio" (bloques de texto libre con
    subtitulos fijos en negrita: Procedimiento, Herramientas/Equipo,
    Normas, Medicion, Forma de Pago, Obligaciones)."""
    fila = tabla.add_row()
    _fijar_anchos_fila(fila.cells, anchos)
    celda_label = fila.cells[0]
    celda_contenido = fila.cells[1]
    for celda_extra in fila.cells[2:]:
        celda_contenido = celda_contenido.merge(celda_extra)

    celda_label.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    parrafo_label = celda_label.paragraphs[0]
    parrafo_label.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_desc = parrafo_label.add_run("DESCRIPCIÓN")
    _aplicar_fuente(run_desc, TAMANO_DIVISOR_PT)
    parrafo_label.add_run().add_break()
    run_mat = parrafo_label.add_run("MATERIAL" if item.get("tipo") != "Servicio" else "SERVICIO")
    _aplicar_fuente(run_mat, TAMANO_DIVISOR_PT)

    if item.get("tipo") == "Servicio":
        primero = True
        for etiqueta, clave in (
            ("PROCEDIMIENTO (Desmontaje/Montaje)", "procedimiento"),
            ("HERRAMIENTAS/EQUIPO", "herramientas_equipo"),
            ("NORMAS", "normas_aplicables"),
            ("MEDICIÓN", "medicion"),
            ("FORMA DE PAGO", "forma_pago"),
            ("OBLIGACIONES", "obligaciones"),
        ):
            _agregar_parrafo_campo(celda_contenido, etiqueta, item.get(clave, ""), primero=primero)
            primero = False
    else:
        parrafo_subtitulo = celda_contenido.paragraphs[0]
        run_subtitulo = parrafo_subtitulo.add_run(item.get("subtitulo_specs") or "MODELO DE EJEMPLO")
        _aplicar_fuente(run_subtitulo, TAMANO_SUBTITULO_PT, resaltado=WD_COLOR_INDEX.BRIGHT_GREEN)

        if item.get("descripcion_material"):
            parrafo_material = celda_contenido.add_paragraph()
            run_material = parrafo_material.add_run(item["descripcion_material"])
            _aplicar_fuente(run_material, TAMANO_PARAMETRO_PT, negrita=False)

        parametros = item.get("parametros", [])
        if parametros:
            tabla_specs = celda_contenido.add_table(rows=0, cols=2)
            tabla_specs.style = "Table Grid"
            tabla_specs._tbl.tblPr.append(
                _bordes_tabla(
                    COLOR_BORDE_TABLA_PARAMETROS, GROSOR_BORDE_TABLA_PARAMETROS, GROSOR_BORDE_TABLA_PARAMETROS
                )
            )
            for parametro in parametros:
                fila_parametro = tabla_specs.add_row()
                run_nombre = fila_parametro.cells[0].paragraphs[0].add_run(parametro.get("nombre", ""))
                _aplicar_fuente(run_nombre, TAMANO_PARAMETRO_PT, negrita=True)
                run_valor = fila_parametro.cells[1].paragraphs[0].add_run(parametro.get("valor", ""))
                _aplicar_fuente(run_valor, TAMANO_PARAMETRO_PT, negrita=False)


def _agregar_fila_separacion_items(tabla, anchos: list[Length]) -> None:
    """Fila vacia entre items: en el modelo es una unica celda fusionada
    (gridSpan sobre toda la fila), no 8 celdas sueltas -- si no se
    fusionan, las lineas verticales de la cuadricula cruzan igual el
    espacio en blanco entre bloques de item."""
    fila = tabla.add_row()
    _fijar_anchos_fila(fila.cells, anchos)
    celda_unica = fila.cells[0]
    for celda_extra in fila.cells[1:]:
        celda_unica = celda_unica.merge(celda_extra)


def _agregar_titulo_seccion(documento: Document, texto: str) -> None:
    """Parrafo suelto (sin tabla/borde) -- se mantiene solo para el
    encabezado "FIRMAS DE RESPONSABILIDAD", seccion que no existe en el
    modelo real y por eso queda fuera de la tabla continua legal."""
    parrafo = documento.add_paragraph()
    run = parrafo.add_run(texto)
    _aplicar_fuente(run, TAMANO_DIVISOR_PT)


def _agregar_campo_legal(documento: Document, etiqueta: str, valor: str) -> None:
    """Campo "Etiqueta: valor" como parrafo suelto (sin tabla/borde) --
    se mantiene solo para el campo FECHA, que tampoco existe en el modelo
    real y por eso queda fuera de la tabla continua legal."""
    parrafo = documento.add_paragraph()
    run_etiqueta = parrafo.add_run(f"{etiqueta}: ")
    _aplicar_fuente(run_etiqueta, TAMANO_LEGAL_PT, negrita=True)
    run_valor = parrafo.add_run(valor or "LLENAR")
    _aplicar_fuente(run_valor, TAMANO_LEGAL_PT, resaltado=WD_COLOR_INDEX.YELLOW if not valor else None, negrita=False)


def _fila_legal(tabla, anchos: list[Length]):
    """Fila de la tabla continua de items/seccion legal con 2 columnas
    logicas: etiqueta (fusiona las 2 primeras columnas del bloque de
    items, ~33% del ancho) y valor (fusiona las 6 restantes, ~67%) --
    misma proporcion visual que las filas de campo del modelo real.
    Al reutilizar `tabla` (la misma tabla de items), la fila hereda
    automaticamente los bordes azul marino institucionales definidos a
    nivel de tabla (w:tblBorders), sin tener que repetirlos por celda."""
    fila = tabla.add_row()
    _fijar_anchos_fila(fila.cells, anchos)
    celda_etiqueta = fila.cells[0].merge(fila.cells[1])
    celda_valor = fila.cells[2]
    for extra in fila.cells[3:]:
        celda_valor = celda_valor.merge(extra)
    celda_etiqueta.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    celda_valor.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    return celda_etiqueta, celda_valor


def _fila_legal_ancho_completo(tabla, anchos: list[Length]):
    """Fila de ancho completo (las 8 columnas fusionadas en una sola
    celda), para los 2 titulos de seccion reales y para los parrafos sin
    etiqueta que el modelo presenta a ancho completo."""
    fila = tabla.add_row()
    _fijar_anchos_fila(fila.cells, anchos)
    celda = fila.cells[0]
    for extra in fila.cells[1:]:
        celda = celda.merge(extra)
    celda.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    return celda


def _agregar_titulo_ancho_legal(tabla, anchos: list[Length], texto: str) -> None:
    """Uno de los 2 unicos titulos de seccion de ancho completo reales
    del modelo: centrado, negrita, sin relleno de color."""
    celda = _fila_legal_ancho_completo(tabla, anchos)
    parrafo = celda.paragraphs[0]
    parrafo.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = parrafo.add_run(texto)
    _aplicar_fuente(run, TAMANO_TITULO_SECCION_ANCHA_PT, negrita=True)


def _agregar_campo_tabla(tabla, anchos: list[Length], etiqueta: str, valor: str):
    """Fila de campo editable por el usuario (etiqueta centrada + valor
    resaltado en amarillo si esta vacio). Devuelve la celda de valor por
    si el llamador necesita agregarle mas contenido (listas, subtablas)."""
    celda_etiqueta, celda_valor = _fila_legal(tabla, anchos)
    parrafo_etiqueta = celda_etiqueta.paragraphs[0]
    parrafo_etiqueta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_etiqueta = parrafo_etiqueta.add_run(etiqueta)
    _aplicar_fuente(run_etiqueta, TAMANO_LEGAL_PT, negrita=False)

    parrafo_valor = celda_valor.paragraphs[0]
    parrafo_valor.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    run_valor = parrafo_valor.add_run(valor or "LLENAR")
    _aplicar_fuente(run_valor, TAMANO_LEGAL_PT, resaltado=WD_COLOR_INDEX.YELLOW if not valor else None, negrita=False)
    return celda_valor


def _iniciar_campo_tabla(tabla, anchos: list[Length], etiqueta: str):
    """Como _agregar_campo_tabla, pero deja la celda de valor vacia para
    que el llamador arme su contenido a mano (texto fijo + listas +
    subtablas), con _agregar_parrafo_legal/_agregar_lista_*/
    _agregar_tabla_simple recibiendo esta celda como `contenedor`."""
    celda_etiqueta, celda_valor = _fila_legal(tabla, anchos)
    parrafo_etiqueta = celda_etiqueta.paragraphs[0]
    parrafo_etiqueta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_etiqueta = parrafo_etiqueta.add_run(etiqueta)
    _aplicar_fuente(run_etiqueta, TAMANO_LEGAL_PT, negrita=False)
    return celda_valor


def _agregar_parrafo_legal(contenedor, texto: str) -> None:
    """`contenedor` puede ser el Document o una celda de tabla (_Cell) --
    ambos exponen add_paragraph() con la misma firma. Si `contenedor` es
    una celda recien creada por _iniciar_campo_tabla (con su unico
    parrafo vacio por defecto), la primera linea reutiliza ese parrafo en
    vez de dejar una linea en blanco arriba del texto."""
    parrafos_existentes = contenedor.paragraphs
    reutilizar_primero = len(parrafos_existentes) == 1 and not parrafos_existentes[0].runs
    for indice, linea in enumerate(texto.split("\n")):
        parrafo = parrafos_existentes[0] if indice == 0 and reutilizar_primero else contenedor.add_paragraph()
        parrafo.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        run = parrafo.add_run(linea)
        _aplicar_fuente(run, TAMANO_LEGAL_PT, negrita=False)


def _agregar_lista_numerada(contenedor, items: list[str]) -> None:
    """Cursiva, igual que el modelo real (atribuciones del administrador)."""
    for numero, texto in enumerate(items, start=1):
        parrafo = contenedor.add_paragraph()
        parrafo.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        run = parrafo.add_run(f"{numero}. {texto}")
        _aplicar_fuente(run, TAMANO_LEGAL_PT, negrita=False, italica=True)


def _agregar_lista_vinetas(contenedor, items: list[str]) -> None:
    """Cursiva, igual que el modelo real (obligaciones adicionales)."""
    for texto in items:
        parrafo = contenedor.add_paragraph()
        parrafo.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        run = parrafo.add_run(f"● {texto}")
        _aplicar_fuente(run, TAMANO_LEGAL_PT, negrita=False, italica=True)


def _agregar_tabla_simple(contenedor, encabezados: list[str], filas: list[list[str]]) -> None:
    """`contenedor` puede ser el Document o una celda de tabla (_Cell) --
    ambos exponen add_table() con la misma firma."""
    tabla = contenedor.add_table(rows=1, cols=len(encabezados))
    tabla.style = "Table Grid"
    for celda, texto in zip(tabla.rows[0].cells, encabezados):
        celda.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        parrafo = celda.paragraphs[0]
        parrafo.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = parrafo.add_run(texto)
        _aplicar_fuente(run, TAMANO_LEGAL_PT)
    for fila_valores in filas:
        fila = tabla.add_row()
        for celda, valor in zip(fila.cells, fila_valores):
            celda.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            parrafo = celda.paragraphs[0]
            parrafo.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = parrafo.add_run(valor)
            _aplicar_fuente(run, TAMANO_LEGAL_PT, negrita=False)


def _agregar_tabla_firmas(documento: Document, firmas: dict) -> None:
    _agregar_titulo_seccion(documento, "FIRMAS DE RESPONSABILIDAD:")
    tabla = documento.add_table(rows=0, cols=3)
    tabla.style = "Table Grid"
    for clave, etiqueta in (("elaborado", "Elaborado por:"), ("revisado", "Revisado por:"), ("aprobado", "Aprobado por:")):
        datos_firma = firmas.get(clave, {})
        fila_etiquetas = tabla.add_row()
        for celda, texto in zip(fila_etiquetas.cells, (etiqueta, "Cargo:", "Firmado por:")):
            run = celda.paragraphs[0].add_run(texto)
            _aplicar_fuente(run, TAMANO_LEGAL_PT)
        fila_valores = tabla.add_row()
        valores = [datos_firma.get("nombre", ""), datos_firma.get("cargo", ""), datos_firma.get("firmado_por", "")]
        for celda, valor in zip(fila_valores.cells, valores):
            run = celda.paragraphs[0].add_run(valor)
            _aplicar_fuente(run, TAMANO_LEGAL_PT, negrita=False)


_PATRON_IMAGEN_BASE64 = re.compile(
    r'src="data:image/(?P<ext>png|jpe?g|gif|bmp|webp);base64,(?P<datos>[^"]+)"', re.IGNORECASE
)


def _extraer_imagenes_base64_a_archivos(html_texto: str, directorio: Path) -> str:
    """htmldocx no soporta URIs de datos (`data:image/...;base64,...`) --
    solo rutas de archivo o URLs http(s); intentar insertarlas tal cual
    falla en silencio y deja un parrafo "<image: ...>" en su lugar. El
    editor TinyMCE (paste_data_images=True) SI incrusta las imagenes
    pegadas como base64, asi que antes de convertir hay que decodificar
    cada una a un archivo temporal real y reemplazar el `src` por esa
    ruta."""
    contador = 0

    def _reemplazar(match: re.Match) -> str:
        nonlocal contador
        contador += 1
        try:
            contenido = base64.b64decode(match.group("datos"))
        except Exception:
            return match.group(0)
        ruta_imagen = directorio / f"imagen_{contador}.{match.group('ext').lower()}"
        ruta_imagen.write_bytes(contenido)
        return f'src="{ruta_imagen.as_posix()}"'

    return _PATRON_IMAGEN_BASE64.sub(_reemplazar, html_texto)


def _aplicar_estilo_institucional_tabla_html(tabla) -> None:
    """Las tablas pegadas desde Excel/Word (via el editor enriquecido) se
    insertan sin ningun estilo -- se les aplica aqui el mismo azul marino
    institucional y la misma fuente Arial que usa el resto del Anexo 1,
    para que no se vean visualmente distintas del resto del documento."""
    tabla._tbl.tblPr.append(_bordes_tabla(COLOR_BORDE_TABLA_ITEMS, GROSOR_BORDE_EXTERIOR, GROSOR_BORDE_INTERIOR))
    for fila in tabla.rows:
        for celda in fila.cells:
            for parrafo in celda.paragraphs:
                for run in parrafo.runs:
                    _aplicar_fuente(run, TAMANO_LEGAL_PT, negrita=run.font.bold or False)


def _insertar_html_en_celda(celda, html_texto: str) -> None:
    """Inserta HTML enriquecido (con posibles tablas e imagenes pegadas
    desde Excel/Word via el editor TinyMCE) en `celda`, usando htmldocx.
    Si la conversion falla (listas anidadas u otras estructuras que
    htmldocx no soporta), degrada de forma segura a texto plano en vez de
    fallar la generacion completa del documento -- la conversion se
    prueba primero en una celda de un documento temporal descartable, asi
    la celda real nunca queda a medio transformar."""
    html_texto = (html_texto or "").strip()
    if not html_texto:
        run = celda.add_paragraph().add_run("LLENAR")
        _aplicar_fuente(run, TAMANO_LEGAL_PT, negrita=False, resaltado=WD_COLOR_INDEX.YELLOW)
        return

    with tempfile.TemporaryDirectory(prefix="anexo1_html_") as directorio_temp:
        html_local = _extraer_imagenes_base64_a_archivos(html_texto, Path(directorio_temp))

        documento_prueba = Document()
        celda_prueba = documento_prueba.add_table(rows=1, cols=1).cell(0, 0)
        try:
            HtmlToDocx().add_html_to_cell(html_local, celda_prueba)
        except Exception:
            texto_plano = BeautifulSoup(html_texto, "html.parser").get_text("\n").strip()
            run = celda.add_paragraph().add_run(texto_plano or "LLENAR")
            _aplicar_fuente(run, TAMANO_LEGAL_PT, negrita=False)
            return

        # La celda de prueba SI se pudo convertir: se copian sus
        # parrafos/tablas ya resueltos a la celda real, antes del parrafo
        # final de esta (una celda siempre debe terminar en parrafo segun
        # el esquema OOXML).
        parrafo_final = celda.paragraphs[-1]._p
        for elemento in list(celda_prueba._tc.iterchildren()):
            if elemento.tag == qn("w:tcPr"):
                continue
            parrafo_final.addprevious(copy.deepcopy(elemento))

    for tabla_insertada in celda.tables:
        _aplicar_estilo_institucional_tabla_html(tabla_insertada)


def _agregar_seccion_legal(documento: Document, datos: dict, tabla, anchos: list[Length]) -> None:
    """Continua la misma `tabla` de items -- la unica tabla continua del
    modelo real, con sus mismos bordes azul marino -- agregando la
    seccion legal como filas de campo (etiqueta centrada + valor) de 2
    columnas. Solo "REQUERIMIENTOS ADICIONALES OBLIGATORIOS" y
    "PARÁMETROS DE EVALUACIÓN Y CALIFICACIÓN" son titulos de ancho
    completo de verdad: se confirmo fila por fila contra el .docx de
    referencia que todo lo demas (Multas, Garantias, Administrador del
    Contrato, Patrimonio, etc.) es un campo normal, no un titulo ancho.

    FECHA y FIRMAS DE RESPONSABILIDAD no existen en ese modelo de
    referencia, asi que quedan fuera de la tabla, como parrafos sueltos
    (ver _agregar_campo_legal/_agregar_titulo_seccion mas arriba)."""
    _agregar_campo_tabla(tabla, anchos, "PRESUPUESTO REFERENCIAL", datos.get("presupuesto_referencial", ""))

    _agregar_titulo_ancho_legal(tabla, anchos, "REQUERIMIENTOS ADICIONALES OBLIGATORIOS")
    requerimientos_cpc = datos.get("requerimientos_cpc") or [{"cpc": "", "descripcion": ""}]
    celda_cpc = _fila_legal_ancho_completo(tabla, anchos)
    _agregar_tabla_simple(
        celda_cpc,
        ["CPC", "DESCRIPCIÓN DEL CPC"],
        [[r.get("cpc", "") or "LLENAR", r.get("descripcion", "") or "LLENAR"] for r in requerimientos_cpc],
    )

    _agregar_campo_tabla(
        tabla,
        anchos,
        "CÓDIGO CPC (DETALLAR EL CÓDIGO Y LA DESCRIPCIÓN DEL DE MAYOR PESO ECONÓMICO DE LA CONTRATACIÓN)",
        datos.get("codigo_cpc_mayor_peso", ""),
    )
    _agregar_campo_tabla(tabla, anchos, "ALCANCE", datos.get("alcance", ""))
    _agregar_campo_tabla(
        tabla, anchos, "PLAZO DE EJECUCIÓN: PARCIALES Y/O TOTAL (EN DÍAS)", datos.get("plazo_ejecucion", "")
    )

    _agregar_campo_tabla(
        tabla, anchos, "1.- PERSONAL TÉCNICO PRINCIPAL", datos.get("personal_tecnico_principal", "")
    )
    _agregar_campo_tabla(
        tabla, anchos, "2.- PERSONAL TÉCNICO AUXILIAR O SECUNDARIO", datos.get("personal_tecnico_auxiliar", "")
    )
    _agregar_campo_tabla(tabla, anchos, "3.- EQUIPO DE TRABAJO", datos.get("equipo_trabajo", ""))
    _agregar_campo_tabla(tabla, anchos, "4.- RECURSOS", datos.get("recursos", ""))

    _agregar_campo_tabla(tabla, anchos, "FORMA Y CONDICIONES DE PAGO", datos.get("forma_condiciones_pago", ""))
    _agregar_campo_tabla(
        tabla, anchos, "LUGAR Y DIRECCIÓN DE ENTREGA/EJECUCIÓN", datos.get("lugar_direccion", "")
    )

    celda_multas = _iniciar_campo_tabla(tabla, anchos, "MULTAS")
    _agregar_parrafo_legal(celda_multas, TEXTO_MULTAS)

    _agregar_campo_tabla(
        tabla, anchos, "i) OBLIGACIONES DE LA ENTIDAD CONTRATANTE", datos.get("obligaciones_entidad", "")
    )
    _agregar_campo_tabla(
        tabla, anchos, "ii) OBLIGACIONES DE LA CONTRATISTA", datos.get("obligaciones_contratista", "")
    )

    _agregar_campo_tabla(
        tabla, anchos, "GARANTÍAS TÉCNICAS, EN EL CASO DE QUE APLIQUE", datos.get("garantias_tecnicas", "")
    )

    celda_garantias = _iniciar_campo_tabla(tabla, anchos, "GARANTÍAS ADICIONALES, EN EL CASO DE QUE APLIQUE")
    _agregar_parrafo_legal(celda_garantias, TEXTO_GARANTIA_FIEL_CUMPLIMIENTO)
    _agregar_parrafo_legal(celda_garantias, TEXTO_GARANTIA_BUEN_USO_ANTICIPO)
    texto_responsabilidad_civil = TEXTO_GARANTIA_RESPONSABILIDAD_CIVIL_PLANTILLA.format(
        objeto=datos.get("objeto_contratacion", "") or "LLENAR",
        monto=datos.get("monto_garantia_responsabilidad_civil", "") or "LLENAR",
    )
    _agregar_parrafo_legal(celda_garantias, texto_responsabilidad_civil)

    _agregar_campo_tabla(
        tabla,
        anchos,
        "VIGENCIA DE LA OFERTA",
        TEXTO_VIGENCIA_OFERTA_PLANTILLA.format(dias=datos.get("vigencia_oferta_dias", "") or "LLENAR"),
    )
    _agregar_campo_tabla(tabla, anchos, "REAJUSTE DE PRECIOS", TEXTO_REAJUSTE_PRECIOS)
    _agregar_campo_tabla(tabla, anchos, "TIPO DE ADJUDICACIÓN", datos.get("tipo_adjudicacion", ""))

    celda_administrador = _iniciar_campo_tabla(tabla, anchos, "ADMINISTRADOR DEL CONTRATO")
    _agregar_parrafo_legal(
        celda_administrador,
        TEXTO_ADMINISTRADOR_INTRO_PLANTILLA.format(
            nombre=datos.get("administrador_nombre", "") or "LLENAR",
            cedula=datos.get("administrador_cedula", "") or "LLENAR",
            cargo=datos.get("administrador_cargo", "") or "LLENAR",
        ),
    )
    _agregar_lista_numerada(celda_administrador, TEXTO_ATRIBUCIONES_ADMINISTRADOR)
    _agregar_parrafo_legal(celda_administrador, TEXTO_ADMINISTRADOR_OBLIGACIONES_INTRO)
    _agregar_lista_vinetas(celda_administrador, TEXTO_ADMINISTRADOR_OBLIGACIONES_ADICIONALES)
    _agregar_parrafo_legal(celda_administrador, TEXTO_ADMINISTRADOR_CIERRE)

    celda_tecnico = _iniciar_campo_tabla(tabla, anchos, "TÉCNICO QUE NO INTERVIENE EN LA CONTRATACIÓN")
    _agregar_parrafo_campo(
        celda_tecnico, "Funcionario", datos.get("tecnico_no_interviene_nombre", ""), primero=True,
        resaltar_si_vacio=True,
    )
    _agregar_parrafo_campo(
        celda_tecnico, "Cargo", datos.get("tecnico_no_interviene_cargo", ""), resaltar_si_vacio=True
    )
    _agregar_parrafo_campo(
        celda_tecnico, "Mail", datos.get("tecnico_no_interviene_correo", ""), resaltar_si_vacio=True
    )
    _agregar_parrafo_campo(
        celda_tecnico, "Dirección", datos.get("direccion_contacto", ""), resaltar_si_vacio=True
    )
    _agregar_parrafo_campo(
        celda_tecnico, "Teléfono", datos.get("telefono_contacto", ""), resaltar_si_vacio=True
    )

    celda_estrategia = _iniciar_campo_tabla(tabla, anchos, "ANÁLISIS PARA DEFINIR LA ESTRATÉGIA DE ADQUISICIÓN")
    _agregar_parrafo_legal(celda_estrategia, TEXTO_ANALISIS_ESTRATEGIA_FIJO)
    run_etiqueta_analisis = celda_estrategia.add_paragraph().add_run("Análisis específico de la contratación:")
    _aplicar_fuente(run_etiqueta_analisis, TAMANO_SUBTITULO_PT, negrita=True)
    # Parrafo final vacio: _insertar_html_en_celda inserta el HTML antes
    # del ULTIMO parrafo de la celda (asi una celda siempre termina en
    # parrafo, por el esquema OOXML) -- sin este, ese "ultimo parrafo"
    # seria el de la etiqueta de arriba, y el HTML quedaria insertado
    # antes de ella en vez de despues.
    celda_estrategia.add_paragraph()
    _insertar_html_en_celda(celda_estrategia, datos.get("analisis_estrategia_html", ""))
    _agregar_campo_tabla(
        tabla, anchos, "PROCESO DE CONTRATACIÓN A APLICAR", datos.get("proceso_contratacion_aplicar", "")
    )

    _agregar_titulo_ancho_legal(tabla, anchos, "PARÁMETROS DE EVALUACIÓN Y CALIFICACIÓN")
    celda_parametros_intro = _fila_legal_ancho_completo(tabla, anchos)
    _agregar_parrafo_legal(celda_parametros_intro, TEXTO_PARAMETROS_EVALUACION_INTRO)

    _agregar_campo_tabla(
        tabla,
        anchos,
        "EXPERIENCIA GENERAL DEL OFERENTE",
        TEXTO_EXPERIENCIA_GENERAL_PLANTILLA.format(
            pct_general=datos.get("pct_experiencia_general", "") or "LLENAR"
        ),
    )
    _agregar_campo_tabla(
        tabla,
        anchos,
        "EXPERIENCIA ESPECÍFICA DEL OFERENTE",
        TEXTO_EXPERIENCIA_ESPECIFICA_PLANTILLA.format(
            pct_especifica=datos.get("pct_experiencia_especifica", "") or "LLENAR"
        ),
    )
    _agregar_campo_tabla(
        tabla,
        anchos,
        "FORMACIÓN DEL PERSONAL TÉCNICO",
        TEXTO_FORMACION_PERSONAL_TECNICO_PLANTILLA.format(
            titulo_profesional=datos.get("titulo_profesional_personal_tecnico", "") or "LLENAR"
        ),
    )
    _agregar_campo_tabla(tabla, anchos, "EXPERIENCIA DEL PERSONAL TÉCNICO", TEXTO_EXPERIENCIA_PERSONAL_TECNICO)
    _agregar_campo_tabla(
        tabla, anchos, "EQUIPO DE TRABAJO/RECURSOS A EVALUAR", datos.get("equipo_trabajo_recursos_evaluar", "")
    )

    celda_certificado = _iniciar_campo_tabla(tabla, anchos, "CERTIFICADO DE PROVEEDOR EXCLUSIVO O AUTORIZADO")
    _agregar_parrafo_legal(celda_certificado, TEXTO_CERTIFICADO_PROVEEDOR_EXCLUSIVO_INTRO)
    _agregar_parrafo_campo(
        celda_certificado, "¿Aplica?", datos.get("certificado_proveedor_exclusivo", "No"), resaltar_si_vacio=True
    )

    patrimonio_aplica = datos.get("patrimonio_aplica", "No")
    celda_patrimonio = _iniciar_campo_tabla(tabla, anchos, "PATRIMONIO")
    _agregar_parrafo_campo(celda_patrimonio, "¿Aplica?", patrimonio_aplica, primero=True, resaltar_si_vacio=True)
    if patrimonio_aplica == "Sí":
        _agregar_parrafo_legal(celda_patrimonio, TEXTO_PATRIMONIO_INTRO)
        run_bienes = celda_patrimonio.add_paragraph().add_run("Bienes y/o Servicios")
        _aplicar_fuente(run_bienes, TAMANO_LEGAL_PT)
        _agregar_tabla_simple(celda_patrimonio, TABLA_PATRIMONIO_ENCABEZADO, TABLA_PATRIMONIO_BIENES_SERVICIOS)
        run_obras = celda_patrimonio.add_paragraph().add_run("Obras")
        _aplicar_fuente(run_obras, TAMANO_LEGAL_PT)
        _agregar_tabla_simple(celda_patrimonio, TABLA_PATRIMONIO_ENCABEZADO, TABLA_PATRIMONIO_OBRAS)

    _agregar_campo_tabla(
        tabla, anchos, "TIEMPO DE EXISTENCIA LEGAL DE PERSONAS JURÍDICAS", TEXTO_TIEMPO_EXISTENCIA_LEGAL
    )

    celda_checklist = _iniciar_campo_tabla(tabla, anchos, "METODOLOGÍA DE EVALUACIÓN DE OFERTA (CUMPLE/NO CUMPLE)")
    _agregar_parrafo_legal(celda_checklist, TEXTO_CHECKLIST_INTRO)
    _agregar_tabla_simple(
        celda_checklist,
        TABLA_CHECKLIST_ENCABEZADO,
        [[criterio, "", "", ""] for criterio in TABLA_CHECKLIST_CRITERIOS_FIJOS],
    )

    _agregar_campo_tabla(
        tabla,
        anchos,
        "EVALUACIÓN DEL ANÁLISIS DE ESTRATEGIA DE ADQUISICIÓN (MEJOR VALOR POR DINERO)",
        datos.get("evaluacion_estrategia_adquisicion", ""),
    )
    _agregar_campo_tabla(
        tabla, anchos, "OTROS PARÁMETROS DE EVALUACIÓN Y CALIFICACIÓN", datos.get("otros_parametros_evaluacion", "")
    )

    celda_puntaje = _iniciar_campo_tabla(tabla, anchos, "METODOLOGÍA DE EVALUACIÓN DE OFERTA POR PUNTAJE")
    _agregar_parrafo_legal(celda_puntaje, TEXTO_PUNTAJE_INTRO)
    _agregar_tabla_simple(celda_puntaje, TABLA_PUNTAJE_ENCABEZADO, TABLA_PUNTAJE_FIJA)

    # FECHA y FIRMAS DE RESPONSABILIDAD no existen en el modelo de
    # referencia -- quedan fuera de la tabla continua, como parrafos
    # sueltos, igual que antes.
    documento.add_paragraph()
    _agregar_campo_legal(documento, "FECHA", datos.get("fecha_documento", ""))
    documento.add_paragraph()
    _agregar_tabla_firmas(documento, datos.get("firmas", {}))


def generar_anexo1(datos: dict, ruta_salida) -> Path:
    documento = Document()
    _configurar_encabezado_pie(documento)
    _agregar_caja_titulo(documento, datos.get("objeto_contratacion", ""))
    documento.add_paragraph()

    tabla = documento.add_table(rows=0, cols=len(ENCABEZADOS_COLUMNAS))
    tabla.style = "Table Grid"
    tabla.autofit = False
    _configurar_propiedades_tabla_items(tabla)
    anchos = [Cm(v) for v in ANCHOS_COLUMNAS_CM]

    for numero, item in enumerate(datos.get("items", []), start=1):
        _agregar_fila_encabezado_item(tabla, anchos)
        _agregar_fila_datos_item(tabla, numero, item, anchos)
        _agregar_fila_divisor_especificaciones(tabla, anchos)
        _agregar_fila_especificaciones_tecnicas(tabla, item, anchos)
        _agregar_fila_separacion_items(tabla, anchos)

    _agregar_seccion_legal(documento, datos, tabla, anchos)

    ruta_salida = Path(ruta_salida)
    documento.save(str(ruta_salida))
    return ruta_salida
