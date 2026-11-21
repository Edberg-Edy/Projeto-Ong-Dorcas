#!/usr/bin/env python3
"""
Implanta as páginas do site do Instituto Filhos e Filhas Dorcas no WordPress
usando a API REST nativa (sem plugin) e uma Senha de Aplicativo.

Só usa a biblioteca padrão do Python 3.8+ (nada para instalar).

Uso rápido:
  export WP_URL="https://filhosefilhasdorcas.org"
  export WP_USER="seu_usuario"
  export WP_APP_PASSWORD="xxxx xxxx xxxx xxxx xxxx xxxx"

  python3 deploy.py --dry-run            # só mostra o que faria
  python3 deploy.py                      # cria só as páginas que NÃO existem
  python3 deploy.py --update             # também sobrescreve as que já existem
  python3 deploy.py --only doe,contato   # limita a algumas páginas (use o slug)
  python3 deploy.py --menu               # cria o menu de navegação (opcional)

Arquivos opcionais na mesma pasta:
  agenda.html     -> iframe do Google Agenda (entra na página Eventos)
  instagram.html  -> código de incorporação do Instagram (entra em Contato)
"""
import argparse
import base64
import html
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.request

AQUI = os.path.dirname(os.path.abspath(__file__))
EMAIL = "filhosefilhasdorcas@gmail.com"

# ---------------------------------------------------------------------------
# CONTEÚDO (texto simples: "## " vira título, linha em branco separa parágrafos)
# ---------------------------------------------------------------------------
PAGINAS = [
    {
        "slug": "inicio",
        "titulo": "Início",
        "texto": """Promovemos a assistência e o desenvolvimento social, acolhendo pessoas e famílias em situação de vulnerabilidade, com acesso a direitos, oportunidades e melhores condições de vida.

## Quem atendemos

Crianças, adolescentes, pessoas idosas, pessoas com deficiência, crianças atípicas, mães atípicas e famílias em situação de vulnerabilidade social, principalmente na Zona Leste de São Paulo.

## O que fazemos

Cursos de qualificação profissional, oficinas de geração de renda, atendimento psicossocial, orientação jurídica, ações de segurança alimentar e atividades de convivência.

## Como ajudar

Você pode doar por Pix, doar roupas e outros itens, ou se voluntariar. Veja as páginas Doe e Voluntariado e parcerias.

## Fale com a gente

Atendimento de segunda a sexta, em horário comercial. Telefone (11) 2011-8464 · filhosefilhasdorcas@gmail.com · Instagram @filhosefilhasdorcas""",
    },
    {
        "slug": "quem-somos",
        "titulo": "Quem Somos",
        "texto": """O Instituto Filhos e Filhas Dorcas tem como missão promover a assistência e o desenvolvimento social, acolhendo pessoas e famílias em situação de vulnerabilidade, garantindo acesso a direitos, oportunidades e melhores condições de vida.

Por meio de projetos sociais, qualificação profissional, segurança alimentar, atendimento psicossocial e ações de inclusão, buscamos fortalecer vínculos familiares e comunitários, promover a autonomia e resgatar a dignidade humana, contribuindo para uma sociedade mais justa, solidária e inclusiva.

## Nosso time

Somos 12 voluntários que atuam de segunda a sexta, em horário comercial, nas atividades, no atendimento às famílias e na execução dos cursos e projetos.

## Onde estamos

R. Fortaleza de Itapema, 268 - Jardim Vera Cruz (Zona Leste), São Paulo - SP, 08330-054""",
    },
    {
        "slug": "projetos-e-cursos",
        "titulo": "Projetos e cursos",
        "texto": """## O que oferecemos

Oferecemos cursos de qualificação profissional, oficinas de geração de renda, atendimento psicossocial, orientação jurídica, ações de segurança alimentar e atividades de convivência.

As novidades, inscrições e datas são divulgadas na página Eventos, nas notícias do site e no nosso Instagram @filhosefilhasdorcas.""",
    },
    {
        "slug": "eventos",
        "titulo": "Eventos",
        "texto": """## Agenda de eventos

Confira abaixo a agenda de cursos, eventos e campanhas do Instituto. As novidades também são divulgadas no nosso Instagram @filhosefilhasdorcas.""",
        "html_extra": "agenda.html",
    },
    {
        "slug": "doe",
        "titulo": "Doe",
        "texto": """## Doação financeira

Faça sua doação pelo Pix do Instituto Filhos e Filhas Dorcas.

Chave Pix (e-mail): filhosefilhasdorcas@gmail.com

## Doação de roupas e outros itens

Aceitamos roupas e outros itens. Para combinar a entrega ou agendar a retirada, escreva para filhosefilhasdorcas@gmail.com.""",
    },
    {
        "slug": "voluntariado-e-parcerias",
        "titulo": "Voluntariado e parcerias",
        "texto": """## Seja voluntário

Quer ajudar no Instituto? Escreva para filhosefilhasdorcas@gmail.com.

## Parcerias

Sua empresa ou organização quer apoiar nosso trabalho? Entre em contato pelo e-mail filhosefilhasdorcas@gmail.com.""",
    },
    {
        "slug": "contato",
        "titulo": "Contato",
        "texto": """Atendimento de segunda a sexta, em horário comercial.

Telefone: (11) 2011-8464
E-mail: filhosefilhasdorcas@gmail.com
Instagram: @filhosefilhasdorcas
Endereço: R. Fortaleza de Itapema, 268 - Jardim Vera Cruz (Zona Leste), São Paulo - SP, 08330-054""",
        "html_extra": "instagram.html",
    },
]

ORDEM_MENU = ["inicio", "quem-somos", "projetos-e-cursos", "eventos",
              "doe", "voluntariado-e-parcerias", "contato"]


# ---------------------------------------------------------------------------
# Conversão do texto simples para blocos do editor do WordPress
# ---------------------------------------------------------------------------
def _inline(s):
    s = html.escape(s, quote=False)
    s = re.sub(r"([\w.+-]+@[\w-]+\.[\w.-]+?)(?=[.,;]?(\s|$|<))",
               r'<a href="mailto:\1">\1</a>', s)
    return s


def para_blocos(texto, html_extra=None):
    blocos = []
    for trecho in re.split(r"\n\s*\n", texto.strip()):
        trecho = trecho.strip()
        if trecho.startswith("## "):
            t = _inline(trecho[3:].strip())
            blocos.append(f'<!-- wp:heading -->\n<h2 class="wp-block-heading">{t}</h2>\n<!-- /wp:heading -->')
        else:
            linhas = "<br>".join(_inline(l.strip()) for l in trecho.splitlines())
            blocos.append(f"<!-- wp:paragraph -->\n<p>{linhas}</p>\n<!-- /wp:paragraph -->")
    if html_extra:
        caminho = os.path.join(AQUI, html_extra)
        if os.path.exists(caminho):
            codigo = open(caminho, encoding="utf-8").read().strip()
            if codigo:
                blocos.append(f"<!-- wp:html -->\n{codigo}\n<!-- /wp:html -->")
    return "\n\n".join(blocos)


# ---------------------------------------------------------------------------
# Cliente mínimo da API REST
# ---------------------------------------------------------------------------
class WP:
    def __init__(self, url, user, senha):
        self.base = url.rstrip("/") + "/wp-json/wp/v2"
        token = base64.b64encode(f"{user}:{senha}".encode()).decode()
        self.cab = {"Authorization": f"Basic {token}",
                    "Content-Type": "application/json",
                    "User-Agent": "dorcas-deploy/1.0"}

    def req(self, metodo, caminho, dados=None):
        corpo = json.dumps(dados).encode() if dados is not None else None
        r = urllib.request.Request(self.base + caminho, data=corpo,
                                   headers=self.cab, method=metodo)
        try:
            with urllib.request.urlopen(r, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            detalhe = e.read().decode(errors="replace")[:400]
            sys.exit(f"Erro {e.code} em {metodo} {caminho}: {detalhe}\n"
                     "Dicas: 401/403 = usuário ou senha de aplicativo errados "
                     "(ou o servidor bloqueia a API); 404 = confira WP_URL.")
        except urllib.error.URLError as e:
            sys.exit(f"Não consegui conectar: {e.reason}")


def normaliza(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="não envia nada")
    ap.add_argument("--update", action="store_true",
                    help="sobrescreve também as páginas que já existem")
    ap.add_argument("--only", help="slugs separados por vírgula")
    ap.add_argument("--menu", action="store_true", help="cria o menu de navegação")
    a = ap.parse_args()

    url = os.environ.get("WP_URL", "https://filhosefilhasdorcas.org")
    user = os.environ.get("WP_USER")
    senha = os.environ.get("WP_APP_PASSWORD")
    if not a.dry_run and not (user and senha):
        sys.exit("Defina WP_USER e WP_APP_PASSWORD (veja o topo do arquivo).")

    alvo = {s.strip() for s in a.only.split(",")} if a.only else None
    paginas = [p for p in PAGINAS if not alvo or p["slug"] in alvo]

    if a.dry_run:
        for p in paginas:
            print(f"--- {p['titulo']} ({p['slug']}) ---")
            print(para_blocos(p["texto"], p.get("html_extra")), "\n")
        print("Dry-run: nada foi enviado.")
        return

    wp = WP(url, user, senha)
    existentes = wp.req("GET", "/pages?per_page=100&status=any&context=edit")
    por_chave = {}
    for e in existentes:
        por_chave[e["slug"]] = e
        por_chave.setdefault(normaliza(e["title"]["raw"]), e)

    ids = {}
    for p in paginas:
        conteudo = para_blocos(p["texto"], p.get("html_extra"))
        atual = por_chave.get(p["slug"]) or por_chave.get(normaliza(p["titulo"]))
        if atual and not a.update:
            print(f"= já existe, mantida: {p['titulo']} (id {atual['id']})")
            ids[p["slug"]] = atual["id"]
        elif atual:
            r = wp.req("POST", f"/pages/{atual['id']}",
                       {"content": conteudo, "status": "publish"})
            print(f"~ atualizada: {p['titulo']} (id {r['id']})")
            ids[p["slug"]] = r["id"]
        else:
            r = wp.req("POST", "/pages", {"title": p["titulo"], "slug": p["slug"],
                                          "content": conteudo, "status": "publish"})
            print(f"+ criada: {p['titulo']} (id {r['id']})")
            ids[p["slug"]] = r["id"]

    if a.menu:
        for s in ORDEM_MENU:  # garante ids das páginas fora do --only
            if s not in ids and s in por_chave:
                ids[s] = por_chave[s]["id"]
        itens = []
        titulos = {p["slug"]: p["titulo"] for p in PAGINAS}
        for s in ORDEM_MENU:
            if s in ids:
                link = f"{url.rstrip('/')}/{s}/"
                attrs = json.dumps({"label": titulos[s], "type": "page",
                                    "id": ids[s], "url": link, "kind": "post-type"},
                                   ensure_ascii=False)
                itens.append(f"<!-- wp:navigation-link {attrs} /-->")
        r = wp.req("POST", "/navigation", {"title": "Menu principal",
                                           "content": "\n".join(itens),
                                           "status": "publish"})
        print(f"+ menu criado (id {r['id']}). Se o cabeçalho não mostrar, "
              "escolha 'Menu principal' em Aparência > Editor > Navegação.")

    print("Pronto.")


if __name__ == "__main__":
    main()
