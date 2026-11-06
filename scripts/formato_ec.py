"""Formato numerico y monetario de Ecuador: punto (.) como separador de
miles y coma (,) como separador decimal (ej. 1234567.89 -> "1.234.567,89"),
moneda en USD con simbolo "$" (ej. "$ 1.234.567,89").

Se implementa a mano en vez de `locale.setlocale(locale.LC_ALL,
"es_EC.UTF-8")` porque ese locale no viene instalado por defecto en la
mayoria de sistemas -- Windows no lo reconoce en absoluto (no tiene
locales POSIX), y en Linux/macOS depende de que el paquete de locales del
SO este generado, lo que la app no puede garantizar en cualquier entorno
donde corra. Una funcion propia es portable sin depender del SO.

Punto de uso: el panel de control y los formularios de app_ui.py, y
scripts/reportes_generator.py (columna "Presupuesto Referencial" del
informe .docx de Reportes) -- todos comparten esta misma funcion, para
que siempre muestren los numeros con la misma convencion."""
import re
import unicodedata

_CARACTERES_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f​-‏ -‮⁠-⁤﻿]")
_ESPACIOS_MULTIPLES = re.compile(r"\s+")


def limpiar_texto_libre(texto, max_len: int = 200) -> str:
    """Sanea un texto libre escrito por el usuario (filtros, palabra clave):
    normaliza Unicode a NFC (conserva ñ y tildes -- no filtra por ASCII),
    elimina caracteres de control y de ancho cero/direccionales (los pega el
    portal o Excel al copiar), colapsa espacios/saltos de linea repetidos,
    recorta bordes y limita la longitud. Devuelve "" si `texto` es None."""
    if texto is None:
        return ""
    limpio = unicodedata.normalize("NFC", str(texto))
    limpio = _CARACTERES_CONTROL.sub("", limpio)
    limpio = _ESPACIOS_MULTIPLES.sub(" ", limpio).strip()
    return limpio[:max_len].rstrip()


def formatear_numero_ec(valor, decimales: int | None = None) -> str:
    """1234567.89 -> "1.234.567,89". Si `decimales` es None, usa 0
    decimales para valores enteros y 2 para valores con parte
    fraccionaria (mismo criterio que antes usaba
    _formatear_numero_especificaciones_tecnicas para cantidades, pero
    ahora con separador de miles)."""
    if valor is None or valor == "":
        return ""
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return str(valor)
    if numero != numero:  # NaN (funciona para float("nan") y np.nan)
        return ""
    if numero in (float("inf"), float("-inf")):
        # int(inf) lanzaria OverflowError mas abajo: un valor infinito no es
        # un monto/cantidad valido, se muestra vacio igual que NaN.
        return ""

    if decimales is None:
        decimales = 0 if numero == int(numero) else 2

    # f"{numero:,.2f}" da el formato en-US ("1,234,567.89"): se
    # intercambian los separadores para obtener la convencion ecuatoriana,
    # usando "§" como marcador intermedio para no confundir una coma ya
    # convertida con un punto todavia sin convertir.
    texto_en_us = f"{numero:,.{decimales}f}"
    return texto_en_us.replace(",", "§").replace(".", ",").replace("§", ".")


def formatear_moneda_ec(valor, decimales: int = 2, simbolo: str = "$") -> str:
    """1234567.89 -> "$ 1.234.567,89". Cadena vacia si `valor` es None/""
    /NaN, igual que el numero sin simbolo (formatear_numero_ec)."""
    numero_formateado = formatear_numero_ec(valor, decimales)
    if not numero_formateado:
        return ""
    return f"{simbolo} {numero_formateado}"


def formatear_porcentaje_ec(valor, decimales: int = 1) -> str:
    """12.345 -> "12,3%" (valor ya en escala 0-100, coma decimal). Cadena
    vacia si `valor` es None/""/NaN/infinito, igual que formatear_numero_ec."""
    numero_formateado = formatear_numero_ec(valor, decimales)
    if not numero_formateado:
        return ""
    return f"{numero_formateado}%"
