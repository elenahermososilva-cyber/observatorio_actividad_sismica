"""Convierte en enlaces pulsables las rutas de archivo citadas entre comillas inversas en los documentos Markdown.

Solo enlaza rutas que existen en el repositorio (archivos versionados o pendientes de versionar; nunca los ignorados por
Git, como `data/raw/` o `.env`), con la ruta relativa desde el documento. Es idempotente: no toca lo que ya es un enlace,
ni los bloques de código, ni los títulos. Los documentos generados por scripts se vuelven a procesar con este mismo script.

    python scripts/enlazar_rutas.py            # procesa docs/*.md, docs/evidencias/*.md y data/README.md
    python scripts/enlazar_rutas.py --dry-run  # solo muestra cuántos enlaces añadiría
    python scripts/enlazar_rutas.py ruta.md …  # procesa solo los documentos indicados
"""

import os
import re
import subprocess
import sys
from pathlib import Path

OS_DIR = Path(__file__).resolve().parents[1]  # observatorio-sismico/
ROOT = OS_DIR.parent  # raíz del repositorio
EXT = {".md", ".py", ".sql", ".json", ".png", ".mjs", ".ts", ".yaml", ".yml", ".html", ".css", ".geojson", ".txt", ".toml", ".example", ".svg", ".js"}
SEARCH_DIRS = ["", "observatorio-sismico", "observatorio-sismico/docs", "observatorio-sismico/docs/evidencias", "observatorio-sismico/frontend",
               "observatorio-sismico/frontend/src/app", "observatorio-sismico/frontend/public", "observatorio-sismico/backend", "observatorio-sismico/tests",
               "observatorio-sismico/scripts", "observatorio-sismico/data"]


def tracked() -> tuple[set[str], set[str]]:
    out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    files = {line.strip() for line in out.splitlines() if line.strip()}
    dirs = {p for f in files for p in (str(Path(f).parents[i]).replace("\\", "/") for i in range(len(Path(f).parents) - 1))}
    return files, dirs


FILES, DIRS = tracked()
BY_NAME: dict[str, list[str]] = {}
for f in FILES:
    BY_NAME.setdefault(Path(f).name, []).append(f)


def resolve(text: str, doc: Path) -> str | None:
    """Ruta del repositorio (relativa a ROOT) a la que se refiere `text`, o None si no existe o es ambigua."""
    t = text.removeprefix("./")
    if not t or t.startswith(("-", "/", "~")) or "://" in t or " " in t or "{" in t or "$" in t:
        return None
    star = "*" in t
    if star:  # «analisis/*.png» → la carpeta que los contiene
        t = t.split("*")[0].rstrip("/")
        if not t:
            return None
    is_dir = text.endswith("/") or star
    t = t.rstrip("/")
    if not is_dir and Path(t).suffix not in EXT and "/" not in t:
        return None
    candidates = [f"{base}/{t}".lstrip("/") for base in SEARCH_DIRS]
    candidates.insert(0, (doc.parent.relative_to(ROOT) / t).as_posix())
    for c in candidates:
        c = os.path.normpath(c).replace("\\", "/")
        if (is_dir and c in DIRS) or (not is_dir and c in FILES) or (not is_dir and c in DIRS and "/" in t):
            return c
    if "/" not in t and not is_dir and len(BY_NAME.get(t, [])) == 1:
        return BY_NAME[t][0]
    return None


LINK = re.compile(r"\[[^\]]*\]\([^)]*\)")  # enlaces ya existentes (se protegen)
CODE = re.compile(r"`([^`\n]+)`")


def linkify(text: str, doc: Path) -> tuple[str, int]:
    count = 0
    out, fenced = [], False
    for line in text.split("\n"):
        stripped = line.lstrip()
        if stripped.startswith("```"):
            fenced = not fenced
            out.append(line)
            continue
        if fenced or stripped.startswith("#") or stripped.startswith("<"):
            out.append(line)
            continue
        protected: list[str] = []

        def hold(m: re.Match) -> str:
            protected.append(m.group(0))
            return f"\u0000{len(protected) - 1}\u0000"

        work = LINK.sub(hold, line)

        def repl(m: re.Match) -> str:
            nonlocal count
            span = m.group(1)
            path_part = span.split("::")[0]
            target = resolve(path_part, doc)
            if target is None:
                return m.group(0)
            rel = os.path.relpath(ROOT / target, doc.parent).replace("\\", "/")
            if (ROOT / target).is_dir():
                rel += "/"
            count += 1
            return f"[`{span}`]({rel})"

        work = CODE.sub(repl, work)
        out.append(re.sub("\u0000(\\d+)\u0000", lambda m: protected[int(m.group(1))], work))
    return "\n".join(out), count


def main(argv: list[str]) -> None:
    dry = "--dry-run" in argv
    paths = [Path(a).resolve() for a in argv if not a.startswith("--")]
    if not paths:
        paths = sorted((OS_DIR / "docs").glob("*.md")) + sorted((OS_DIR / "docs" / "evidencias").glob("*.md")) + [OS_DIR / "data" / "README.md"]
    total = 0
    for p in paths:
        if "curso" in p.parts:  # material del curso: no se edita
            continue
        raw = p.read_bytes().decode("utf-8")
        crlf = "\r\n" in raw
        new, n = linkify(raw.replace("\r\n", "\n"), p)
        if n:
            total += n
            print(f"{p.relative_to(ROOT)}: +{n}")
            if not dry:
                p.write_bytes((new.replace("\n", "\r\n") if crlf else new).encode("utf-8"))
    print(f"total: {total} enlaces{' (simulación)' if dry else ''}")


if __name__ == "__main__":
    main(sys.argv[1:])
