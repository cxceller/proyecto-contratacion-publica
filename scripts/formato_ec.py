"""Formato numerico y monetario de Ecuador: punto (.) como separador de
miles y coma (,) como separador decimal (ej. 1234567.89 -> "1.234.567,89"),
moneda en USD con simbolo "$" (ej. "$ 1.234.567,89").

Se implementa a mano en vez de `locale.setlocale(locale.LC_ALL,
"es_EC.UTF-8")` porque ese locale no viene instalado por defecto en la
mayoria de sistemas -- Windows no lo reconoce en absoluto (no tiene
locales POSIX), y en Linux/macOS depende de que el paquete de locales del
SO este generado, lo que la app no puede garantizar en cualquier entorno
donde corra. Una funcion propia es portable sin depender del SO.

Punto de uso compartido entre el backend (scripts/report_generator.py,
via src/api_reportes.py) y el frontend (app_ui.py), para que el
panel de control, los formularios y los documentos Word generados
siempre muestren los numeros con la misma convencion."""


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
