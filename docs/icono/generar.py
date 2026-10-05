"""Icono de Omada IP Groups: un grupo (recuadro discontinuo) con tres
equipos conectados, en blanco sobre un cuadrado redondeado azul."""
import math
import sys
from PIL import Image, ImageChops, ImageDraw

def dibujar(lado: int) -> Image.Image:
    S = 4  # sobremuestreo para bordes suaves
    W = lado * S
    u = W / 256  # unidades de un lienzo de 256

    # Fondo: cuadrado redondeado con un degradado vertical suave.
    fondo = Image.new("RGBA", (W, W))
    top, bottom = (33, 150, 243), (13, 71, 161)
    df = ImageDraw.Draw(fondo)
    for y in range(W):
        t = y / (W - 1)
        df.line([(0, y), (W, y)], fill=tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)) + (255,))
    mascara = Image.new("L", (W, W), 0)
    ImageDraw.Draw(mascara).rounded_rectangle([0, 0, W - 1, W - 1], radius=56 * u, fill=255)
    img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    img.paste(fondo, (0, 0), mascara)

    # Dibujo en blanco sobre una capa de alfa.
    capa = Image.new("L", (W, W), 0)
    d = ImageDraw.Draw(capa)

    # Grupo: recuadro redondeado, luego se recortan los huecos.
    x0, y0, x1, y1, r = 40 * u, 40 * u, 216 * u, 216 * u, 34 * u
    grosor = 10 * u
    contorno = Image.new("L", (W, W), 0)
    ImageDraw.Draw(contorno).rounded_rectangle([x0, y0, x1, y1], radius=r, outline=255, width=round(grosor))
    # Recorrido por el centro del trazo, para colocar los huecos.
    rc = r - grosor / 2
    a0, b0, a1, b1 = x0 + grosor / 2, y0 + grosor / 2, x1 - grosor / 2, y1 - grosor / 2
    puntos = []
    def recta(p, q, n=200):
        puntos.extend((p[0] + (q[0] - p[0]) * k / n, p[1] + (q[1] - p[1]) * k / n) for k in range(n))
    def arco(cx, cy, ang0, n=200):
        puntos.extend((cx + rc * math.cos(math.radians(ang0 + 90 * k / n)), cy + rc * math.sin(math.radians(ang0 + 90 * k / n))) for k in range(n))
    recta((a0 + rc, b0), (a1 - rc, b0)); arco(a1 - rc, b0 + rc, -90)
    recta((a1, b0 + rc), (a1, b1 - rc)); arco(a1 - rc, b1 - rc, 0)
    recta((a1 - rc, b1), (a0 + rc, b1)); arco(a0 + rc, b1 - rc, 90)
    recta((a0, b1 - rc), (a0, b0 + rc)); arco(a0 + rc, b0 + rc, 180)
    puntos.append(puntos[0])
    acum = [0.0]
    for p, q in zip(puntos, puntos[1:]):
        acum.append(acum[-1] + math.dist(p, q))
    total = acum[-1]
    n_guiones = 16
    periodo = total / n_guiones
    hueco = periodo * 0.36
    huecos = Image.new("L", (W, W), 0)
    dh = ImageDraw.Draw(huecos)
    j = 0
    for k in range(n_guiones):
        s = (k + 0.5) * periodo  # huecos centrados entre guiones
        while acum[j + 1] < s:
            j += 1
        p, q = puntos[j], puntos[j + 1]
        tx, ty = (q[0] - p[0]), (q[1] - p[1])
        n = math.hypot(tx, ty) or 1
        tx, ty = tx / n, ty / n
        nx, ny = -ty, tx
        f = (s - acum[j]) / (acum[j + 1] - acum[j] or 1)
        cx, cy = p[0] + (q[0] - p[0]) * f, p[1] + (q[1] - p[1]) * f
        h, g = hueco / 2, grosor * 1.5
        dh.polygon([
            (cx - tx * h - nx * g, cy - ty * h - ny * g),
            (cx + tx * h - nx * g, cy + ty * h - ny * g),
            (cx + tx * h + nx * g, cy + ty * h + ny * g),
            (cx - tx * h + nx * g, cy - ty * h + ny * g),
        ], fill=255)
    capa = ImageChops.lighter(capa, ImageChops.subtract(contorno, huecos))
    d = ImageDraw.Draw(capa)

    # Tres equipos conectados en triángulo.
    nodos = [(128 * u, 90 * u), (88 * u, 162 * u), (168 * u, 162 * u)]
    for a, b in ((0, 1), (0, 2), (1, 2)):
        d.line([nodos[a], nodos[b]], fill=255, width=round(9 * u))
    for cx, cy in nodos:
        rn = 19 * u
        d.ellipse([cx - rn, cy - rn, cx + rn, cy + rn], fill=255)

    blanco = Image.new("RGBA", (W, W), (255, 255, 255, 255))
    img.paste(blanco, (0, 0), capa)
    return img.resize((lado, lado), Image.LANCZOS)

destino = sys.argv[1]
dibujar(256).save(f"{destino}/icon.png", optimize=True)
dibujar(512).save(f"{destino}/icon@2x.png", optimize=True)
print("ok")
