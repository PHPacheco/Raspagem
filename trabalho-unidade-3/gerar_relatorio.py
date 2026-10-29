from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from PIL import Image as PILImage
from PIL import ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    KeepTogether,
    LongTable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
WORK = Path(__file__).resolve().parent
RESULTS = WORK / "output" / "results" / "resumo.json"
DATABASE = ROOT / "data" / "recipes.sqlite"
FIGURES = WORK / "output" / "figures"
OUTPUT = WORK / "output" / "pdf" / "relatorio-unidade-3-preenchido.pdf"

BLUE = colors.HexColor("#173F5F")
TEAL = colors.HexColor("#1F7A8C")
LIGHT_BLUE = colors.HexColor("#EAF3F7")
LIGHT_GRAY = colors.HexColor("#F4F6F8")
MID_GRAY = colors.HexColor("#6B7280")
INK = colors.HexColor("#1F2937")
GREEN = colors.HexColor("#2E7D5B")
ORANGE = colors.HexColor("#C46A24")
RED = colors.HexColor("#B4443E")

PALETTE = [
    "#1763DC",
    "#00856F",
    "#AB571E",
    "#8455A1",
    "#B42318",
    "#126D89",
    "#65752C",
    "#A43D78",
]


def register_fonts() -> tuple[str, str]:
    regular = Path(r"C:\Windows\Fonts\arial.ttf")
    bold = Path(r"C:\Windows\Fonts\arialbd.ttf")
    if regular.exists() and bold.exists():
        pdfmetrics.registerFont(TTFont("Arial", regular))
        pdfmetrics.registerFont(TTFont("Arial-Bold", bold))
        return "Arial", "Arial-Bold"
    return "Helvetica", "Helvetica-Bold"


FONT, FONT_BOLD = register_fonts()


def pil_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = Path(r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf")
    if path.exists():
        return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def draw_bar_chart(
    path: Path,
    title: str,
    categories: list[str],
    series: list[tuple[str, list[float], str]],
    maximum: float,
    percent: bool = False,
) -> None:
    width, height = 1500, 820
    image = PILImage.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.text((70, 42), title, fill="#1F2937", font=pil_font(38, True))
    left, top, right, bottom = 150, 145, 1425, 670
    draw.line((left, top, left, bottom), fill="#4B5563", width=3)
    draw.line((left, bottom, right, bottom), fill="#4B5563", width=3)
    for step in range(6):
        value = maximum * step / 5
        y = bottom - (bottom - top) * step / 5
        draw.line((left, y, right, y), fill="#E5E7EB", width=2)
        label = f"{value * 100:.0f}%" if percent else f"{value:.0f}"
        draw.text((35, y - 15), label, fill="#6B7280", font=pil_font(23))
    group_width = (right - left) / max(1, len(categories))
    bar_width = min(105, group_width / (len(series) + 1))
    for category_index, category in enumerate(categories):
        center = left + group_width * (category_index + 0.5)
        for series_index, (name, values, color) in enumerate(series):
            value = values[category_index]
            x0 = center + (series_index - (len(series) - 1) / 2) * bar_width - bar_width * 0.38
            x1 = x0 + bar_width * 0.76
            y0 = bottom - (bottom - top) * value / maximum
            draw.rounded_rectangle((x0, y0, x1, bottom), radius=8, fill=color)
            label = f"{value * 100:.1f}%" if percent else f"{value:.0f}"
            draw.text((x0, y0 - 32), label, fill="#374151", font=pil_font(21))
        bbox = draw.textbbox((0, 0), category, font=pil_font(24, True))
        draw.text((center - (bbox[2] - bbox[0]) / 2, bottom + 25), category, fill="#374151", font=pil_font(24, True))
    legend_x = 980
    for index, (name, _, color) in enumerate(series):
        x = legend_x + index * 210
        draw.rounded_rectangle((x, 750, x + 34, 784), radius=5, fill=color)
        draw.text((x + 45, 751), name, fill="#374151", font=pil_font(22))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, quality=95)


def draw_cluster_scatter(path: Path, run_id: int) -> None:
    connection = sqlite3.connect(DATABASE)
    rows = connection.execute(
        """
        SELECT x, y, cluster_label
        FROM document_vectors
        WHERE run_id = ?
        ORDER BY cluster_label
        """,
        (run_id,),
    ).fetchall()
    connection.close()
    width, height = 1500, 900
    image = PILImage.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.text((70, 40), "Projeção PCA dos clusters TF-IDF", fill="#1F2937", font=pil_font(38, True))
    draw.text(
        (70, 92),
        "Cada ponto representa uma receita; as cores indicam os sete clusters.",
        fill="#6B7280",
        font=pil_font(24),
    )
    left, top, right, bottom = 120, 155, 1160, 790
    xs = [float(row[0]) for row in rows]
    ys = [float(row[1]) for row in rows]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    x_span = x_max - x_min or 1.0
    y_span = y_max - y_min or 1.0
    draw.rectangle((left, top, right, bottom), outline="#9CA3AF", width=3)
    draw.line((left, (top + bottom) / 2, right, (top + bottom) / 2), fill="#E5E7EB", width=2)
    draw.line(((left + right) / 2, top, (left + right) / 2, bottom), fill="#E5E7EB", width=2)
    counts: dict[int, int] = {}
    for x, y, label in rows:
        label = int(label)
        counts[label] = counts.get(label, 0) + 1
        px = left + (float(x) - x_min) / x_span * (right - left)
        py = bottom - (float(y) - y_min) / y_span * (bottom - top)
        color = PALETTE[label % len(PALETTE)]
        draw.ellipse((px - 9, py - 9, px + 9, py + 9), fill=color, outline="white", width=2)
    draw.text((530, 820), "Componente principal 1", fill="#4B5563", font=pil_font(23, True))
    draw.text((15, 450), "CP 2", fill="#4B5563", font=pil_font(23, True))
    for index, label in enumerate(sorted(counts)):
        y = 190 + index * 70
        color = PALETTE[label % len(PALETTE)]
        draw.ellipse((1225, y, 1257, y + 32), fill=color)
        draw.text((1275, y), f"Cluster {label}: {counts[label]} receitas", fill="#374151", font=pil_font(23))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, quality=95)


def draw_linguistic_chart(path: Path, data: dict[str, object]) -> None:
    sentiments = {item["polarity"]: int(item["count"]) for item in data["sentiments"]}
    entities = {item["entity_type"]: int(item["count"]) for item in data["entities"]}
    width, height = 1500, 880
    image = PILImage.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.text((70, 40), "Cobertura da análise linguística", fill="#1F2937", font=pil_font(38, True))
    draw.text((70, 100), "Sentimentos por unidade textual", fill="#374151", font=pil_font(27, True))
    sentiment_items = [("Neutro", sentiments.get("neutro", 0), "#64748B"), ("Positivo", sentiments.get("positivo", 0), "#2E7D5B"), ("Negativo", sentiments.get("negativo", 0), "#B4443E")]
    max_sentiment = max(value for _, value, _ in sentiment_items) or 1
    for index, (label, value, color) in enumerate(sentiment_items):
        y = 165 + index * 72
        draw.text((70, y), label, fill="#374151", font=pil_font(24))
        draw.rounded_rectangle((230, y, 720, y + 34), radius=8, fill="#EEF2F7")
        draw.rounded_rectangle((230, y, 230 + 490 * value / max_sentiment, y + 34), radius=8, fill=color)
        draw.text((740, y), str(value), fill="#374151", font=pil_font(24, True))
    draw.text((70, 430), "Entidades reconhecidas", fill="#374151", font=pil_font(27, True))
    entity_items = sorted(entities.items(), key=lambda item: -item[1])
    max_entity = max(value for _, value in entity_items) or 1
    for index, (label, value) in enumerate(entity_items):
        y = 495 + index * 50
        draw.text((70, y), label, fill="#374151", font=pil_font(21))
        draw.rounded_rectangle((300, y, 1220, y + 28), radius=7, fill="#EEF2F7")
        draw.rounded_rectangle((300, y, 300 + 920 * value / max_entity, y + 28), radius=7, fill="#1763DC")
        draw.text((1240, y), str(value), fill="#374151", font=pil_font(21, True))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, quality=95)


def styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "Title",
            parent=base["Title"],
            fontName=FONT_BOLD,
            fontSize=25,
            leading=31,
            textColor=BLUE,
            alignment=TA_CENTER,
            spaceAfter=18,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle",
            parent=base["Normal"],
            fontName=FONT,
            fontSize=13,
            leading=18,
            textColor=MID_GRAY,
            alignment=TA_CENTER,
        ),
        "h1": ParagraphStyle(
            "H1",
            parent=base["Heading1"],
            fontName=FONT_BOLD,
            fontSize=17,
            leading=22,
            textColor=BLUE,
            spaceBefore=8,
            spaceAfter=10,
        ),
        "h2": ParagraphStyle(
            "H2",
            parent=base["Heading2"],
            fontName=FONT_BOLD,
            fontSize=13.5,
            leading=18,
            textColor=TEAL,
            spaceBefore=8,
            spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=10.2,
            leading=14.5,
            textColor=INK,
            alignment=TA_JUSTIFY,
            spaceAfter=8,
        ),
        "small": ParagraphStyle(
            "Small",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=8.2,
            leading=11,
            textColor=INK,
            alignment=TA_LEFT,
        ),
        "note": ParagraphStyle(
            "Note",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=9.2,
            leading=13,
            textColor=colors.HexColor("#374151"),
            backColor=LIGHT_BLUE,
            borderColor=TEAL,
            borderWidth=0.8,
            borderPadding=8,
            spaceBefore=6,
            spaceAfter=10,
        ),
    }


STYLES = styles()


def p(text: str, style: str = "body") -> Paragraph:
    return Paragraph(text, STYLES[style])


def table(data, widths, header=True, small=True) -> Table:
    paragraph_style = STYLES["small"] if small else STYLES["body"]
    header_style = ParagraphStyle(
        "TableHeader",
        parent=STYLES["small"],
        fontName=FONT_BOLD,
        textColor=colors.white,
    )
    formatted = []
    for row_index, row in enumerate(data):
        cell_style = header_style if header and row_index == 0 else paragraph_style
        formatted.append([
            cell if hasattr(cell, "wrap") else Paragraph(str(cell), cell_style)
            for cell in row
        ])
    result = LongTable(formatted, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    commands = [
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#AAB2BD")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    if header:
        commands += [
            ("BACKGROUND", (0, 0), (-1, 0), BLUE),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ]
    for row in range(1 if header else 0, len(data)):
        if row % 2 == 0:
            commands.append(("BACKGROUND", (0, row), (-1, row), LIGHT_GRAY))
    result.setStyle(TableStyle(commands))
    return result


def header_footer(canvas, document) -> None:
    canvas.saveState()
    if document.page > 1:
        canvas.setStrokeColor(colors.HexColor("#D5DAE1"))
        canvas.line(1.7 * cm, A4[1] - 1.3 * cm, A4[0] - 1.7 * cm, A4[1] - 1.3 * cm)
        canvas.setFont(FONT, 8)
        canvas.setFillColor(MID_GRAY)
        canvas.drawString(1.7 * cm, A4[1] - 1.05 * cm, "Processamento de Linguagem Natural - Trabalho da Unidade 3")
        canvas.drawRightString(A4[0] - 1.7 * cm, 1.0 * cm, f"Página {document.page}")
    canvas.restoreState()


def format_score(value: float) -> str:
    return f"{value:.4f}".replace(".", ",")


def build_pdf(data: dict[str, object]) -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        rightMargin=1.7 * cm,
        leftMargin=1.7 * cm,
        topMargin=1.8 * cm,
        bottomMargin=1.6 * cm,
        title="PLN - Trabalho da Unidade 3 - Respostas",
        author="Pedro Pacheco",
        subject="Avaliação de representações e tarefas de Processamento de Linguagem Natural",
    )
    story = []

    story += [Spacer(1, 2.1 * cm)]
    story += [p("UNIVERSIDADE REGIONAL DE BLUMENAU", "subtitle")]
    story += [Spacer(1, 0.3 * cm), p("CENTRO DE CIÊNCIAS EXATAS E NATURAIS", "subtitle")]
    story += [Spacer(1, 0.3 * cm), p("CURSO DE CIÊNCIA DA COMPUTAÇÃO", "subtitle")]
    story += [Spacer(1, 1.8 * cm), p("Processamento de Linguagem Natural", "subtitle")]
    story += [Spacer(1, 0.25 * cm), p("2026/2", "subtitle")]
    story += [Spacer(1, 2.0 * cm), p("Trabalho da Unidade 3", "title")]
    story += [p("Avaliação de representações textuais e técnicas de PLN no domínio de receitas", "subtitle")]
    story += [Spacer(1, 2.4 * cm), p("Acadêmico: Pedro Pacheco", "subtitle")]
    story += [Spacer(1, 0.3 * cm), p("Blumenau - 29 de outubro de 2026", "subtitle")]
    story += [PageBreak()]

    corpus = data["corpus"]
    story += [p("1. Escopo e dados analisados", "h1")]
    story += [p(
        f"A entrega usa o banco SQLite do projeto de coleta acadêmica de receitas. O corpus contém "
        f"<b>{corpus['recipes']} receitas</b>, {corpus['text_units']} unidades textuais preparadas e "
        f"vocabulário de {corpus['vocabulary']} termos. Há rótulo de dificuldade para todas as receitas, "
        f"rótulo de custo para {corpus['cost_labels']} e metadados de avaliação e tempo para "
        f"{corpus['ratings']} e {corpus['preparation_times']} receitas, respectivamente."
    )]
    story += [p(
        "Os textos combinam títulos, descrições, ingredientes e etapas de preparo. A preparação inclui "
        "normalização, tokenização, remoção seletiva de stopwords, stemming e lematização heurística. "
        "Todos os resultados apresentados abaixo foram recalculados localmente ou lidos das execuções "
        "persistidas no banco do projeto."
    )]
    story += [p(
        "A coluna Word2Vec do enunciado não foi marcada como realizada porque o projeto usa uma "
        "representação densa local baseada em coocorrência, PPMI e projeção determinística de 32 dimensões. "
        "Ela é útil para comparação, mas não deve ser chamada de Word2Vec. BERT também não foi executado, "
        "pois não existe modelo Transformer versionado no ambiente reproduzível do projeto.",
        "note",
    )]

    story += [p("1.1 Matriz das atividades realizadas", "h2")]
    matrix_data = [
        ["Tarefa", "BoW", "TF-IDF", "Word2Vec", "BERT"],
        ["Clusterização + PCA + visualização", "Realizada", "Realizada", "Não: substituto PPMI 32D", "Não: sem modelo local"],
        ["Busca e recomendação", "Realizada", "Realizada", "Não: substituto PPMI 32D", "Não: sem modelo local"],
        ["Classificação", "Realizada", "Realizada", "Não: substituto PPMI 32D", "Não: sem modelo local"],
    ]
    story += [table(matrix_data, [4.0 * cm, 2.2 * cm, 2.3 * cm, 4.0 * cm, 3.6 * cm])]
    story += [Spacer(1, 0.3 * cm)]
    story += [p(
        "Atividades adicionais: análise de sentimentos, reconhecimento de entidades nomeadas e extração "
        "de relações foram realizadas com regras determinísticas e léxicos de domínio."
    )]

    story += [PageBreak(), p("2. Clusterização e visualização", "h1")]
    clustering = data["clustering"]
    metrics_data = [["Representação", "Clusters", "Silhouette", "Leitura principal"]]
    metrics_data.append(["BoW", clustering["BoW"]["cluster_count"], format_score(clustering["BoW"]["silhouette"]), "Dois grupos amplos; termos genéricos dominam."])
    metrics_data.append(["TF-IDF", clustering["TF-IDF"]["cluster_count"], format_score(clustering["TF-IDF"]["silhouette"]), "Sete temas culinários interpretáveis."])
    metrics_data.append(["PPMI 32D", clustering["PPMI-32D"]["cluster_count"], format_score(clustering["PPMI-32D"]["silhouette"]), "Melhor separação geométrica; grupos mais amplos."])
    story += [table(metrics_data, [3.1 * cm, 2.3 * cm, 2.6 * cm, 7.7 * cm])]
    story += [Spacer(1, 0.25 * cm)]
    story += [p(
        "O PPMI 32D obteve o maior silhouette (0,1019) com quatro clusters, portanto apresenta a melhor "
        "separação geométrica. Entretanto, o TF-IDF produziu os grupos mais representativos para leitura "
        "humana: frutos do mar; pratos com queijo e batata; frango e frituras; massas, bolos e banana; "
        "salmão; receitas de pressão e costela; e preparações com carne suína. Por isso, a escolha final é "
        "<b>TF-IDF com sete clusters</b>. O silhouette baixo (0,0228) mostra sobreposição entre receitas, "
        "algo esperado porque ingredientes e verbos de preparo são compartilhados entre categorias."
    )]
    story += [Image(str(FIGURES / "clusters-tfidf.png"), width=16.2 * cm, height=9.72 * cm)]
    story += [p(
        "Figura 1 - Projeção bidimensional das coordenadas principais persistidas para a matriz TF-IDF. "
        "A proximidade visual ajuda a localizar sobreposição entre temas, mas não substitui a inspeção "
        "dos termos de cada cluster.",
        "small",
    )]

    story += [PageBreak(), p("3. Busca e recomendação", "h1")]
    story += [p(
        "Foram avaliadas duas consultas. BoW e TF-IDF usam similaridade de cosseno entre a consulta e os "
        "documentos. O PPMI 32D usa a média dos vetores dos termos reconhecidos. O top-3 corresponde às "
        "três primeiras linhas de cada top-5."
    )]
    for query, results in data["searches"].items():
        story += [p(f"Consulta: <b>{query}</b>", "h2")]
        rows = [["Representação", "Posição", "Receita", "Similaridade"]]
        for representation in ("BoW", "TF-IDF", "PPMI-32D"):
            for rank, item in enumerate(results[representation], 1):
                rows.append([representation, rank, item["title"], format_score(item["score"])])
        story += [table(rows, [2.5 * cm, 1.7 * cm, 9.6 * cm, 2.4 * cm])]
        story += [Spacer(1, 0.2 * cm)]
    story += [p(
        "Na consulta <i>carne com cebola</i>, BoW e TF-IDF retornam apenas receitas de carne nas primeiras "
        "cinco posições. O PPMI recupera três receitas de carne no top-3, mas introduz Panqueca de banana "
        "fit e Estrogonofe de camarão no top-5, o que reduz a precisão. Para <i>sobremesa de banana</i>, "
        "TF-IDF apresenta o conjunto mais consistente; o PPMI captura receitas próximas, mas inclui Pão "
        "sem glúten por contexto compartilhado. Em um contexto real, TF-IDF é o melhor ponto de partida. "
        "A solução pode melhorar com filtros por categoria, tempo e custo, realimentação do usuário e uma "
        "fusão de escores lexicais e densos."
    )]

    story += [PageBreak(), p("4. Classificação", "h1")]
    classification = data["classification"]
    story += [p(
        "O alvo inicial, dificuldade, é inadequado para avaliação: as 120 receitas estão rotuladas como "
        "<i>fácil</i>. Um modelo que sempre escolhesse essa classe teria 100% de acurácia sem aprender "
        "qualquer distinção. Para obter um experimento válido, foi usado o custo, disponível em 52 "
        "receitas: 34 de custo médio, 11 de custo alto e 7 de custo baixo. A divisão estratificada e "
        "determinística contém 39 exemplos de treino e 13 de teste."
    )]
    story += [p(
        "O mesmo classificador de centroide mais próximo por cosseno foi aplicado às três representações. "
        "Isso isola o efeito da representação, embora o conjunto de teste pequeno torne os resultados "
        "exploratórios."
    )]
    classification_rows = [["Representação", "Acurácia", "Precisão macro", "Recall macro", "F1 macro"]]
    for representation in ("BoW", "TF-IDF", "PPMI-32D"):
        metrics = classification["representations"][representation]
        classification_rows.append([
            representation,
            format_score(metrics["accuracy"]),
            format_score(metrics["macro_precision"]),
            format_score(metrics["macro_recall"]),
            format_score(metrics["macro_f1"]),
        ])
    story += [table(classification_rows, [3.2 * cm, 3.0 * cm, 3.3 * cm, 3.0 * cm, 3.0 * cm])]
    story += [Spacer(1, 0.3 * cm)]
    story += [Image(str(FIGURES / "comparacao-classificacao.png"), width=16.2 * cm, height=8.86 * cm)]
    story += [p(
        "Figura 2 - BoW e TF-IDF empataram com acurácia de 76,92% e F1 macro de 0,7190. O PPMI 32D "
        "obteve 61,54% e F1 macro de 0,5353. Neste corpus, a informação lexical direta favorece a "
        "classificação de custo. Ainda assim, 52 rótulos são insuficientes para uma conclusão geral; "
        "validação cruzada e mais exemplos por classe são os próximos passos.",
        "small",
    )]

    story += [PageBreak(), p("5. Sentimentos, entidades e relações", "h1")]
    linguistic = data["linguistic"]
    run = linguistic["run"]
    story += [p(
        f"As três tarefas são aplicáveis ao domínio. A execução mais recente processou {run['document_count']} "
        f"documentos e {run['sentence_count']} sentenças, produzindo {run['sentiment_count']} análises de "
        f"sentimento, {run['entity_count']} entidades e {run['relation_count']} relações."
    )]
    story += [Image(str(FIGURES / "analise-linguistica.png"), width=16.2 * cm, height=9.5 * cm)]
    story += [p(
        "Figura 3 - A neutralidade domina instruções e listas de ingredientes. Quantidades e ingredientes "
        "são as entidades mais frequentes, o que confirma a adequação das regras ao domínio.",
        "small",
    )]
    story += [p("5.1 Análise de sentimentos", "h2")]
    story += [p(
        "Foram classificadas 2.421 unidades como neutras, 75 como positivas e 9 como negativas. O resultado "
        "é coerente com textos instrucionais, mas deve ser interpretado como tom linguístico, não como "
        "avaliação do sabor. Expressões como <i>delicioso</i>, <i>perfeito</i> e <i>não gostei</i> ativam o "
        "léxico; ingredientes e comandos normalmente permanecem neutros."
    )]
    story += [p("5.2 Entidades nomeadas", "h2")]
    entity_rows = [["Tipo", "Quantidade"]] + [
        [item["entity_type"], item["count"]] for item in linguistic["entities"]
    ]
    story += [table(entity_rows, [7.8 * cm, 4.0 * cm])]
    story += [p(
        "O reconhecimento identifica QUANTITY, INGREDIENT, UNIT, UTENSIL, DURATION, CATEGORY e TEMPERATURE. "
        "Exemplos incluem '500 g de camarão médio' como INGREDIENT, 'xícara' como UNIT e '60 minutos' "
        "como DURATION. Esses campos podem alimentar filtros e comparações nutricionais futuras."
    )]
    relation_rows = [["Relação", "Ocorrências", "Confiança média"]] + [
        [item["relation"], item["count"], format_score(item["average_confidence"])]
        for item in linguistic["relations"][:10]
    ]
    story += [KeepTogether([
        p("5.3 Extração de relações", "h2"),
        table(relation_rows, [7.8 * cm, 3.2 * cm, 4.2 * cm]),
        p(
            "As relações estruturais são as mais confiáveis: receita-tem_ingrediente, receita-usa_utensilio e "
            "receita-pertence_categoria. Relações ação-objeto, como refogar-metade, misturar-ingredientes e "
            "levar-forno, têm confiança 0,65 e exigem revisão, pois o baseline raso também captura verbos ou "
            "conectivos pouco informativos. A principal melhoria é substituir as regras por análise sintática "
            "treinada para português e normalizar os objetos para entidades reconhecidas."
        ),
    ])]

    story += [PageBreak(), p("6. Contribuição para o projeto da Unidade 1", "h1")]
    story += [p(
        "As técnicas estudadas concretizam a proposta de transformar uma coleta de receitas em um sistema "
        "consultável. A preparação textual e a deduplicação tornam os dados comparáveis; TF-IDF e "
        "similaridade suportam busca e recomendação; clusters ajudam a descobrir temas sem rótulos; a "
        "classificação pode preencher metadados de custo quando houver amostras suficientes; entidades e "
        "relações convertem texto livre em filtros estruturados."
    )]
    story += [p(
        "O resultado mais útil no estágio atual é a busca híbrida: recuperar por TF-IDF, aplicar filtros de "
        "categoria, custo e tempo e usar o embedding denso como sinal secundário. Essa combinação reduz "
        "retornos semanticamente vagos e aproveita os campos já extraídos. A análise também mostrou os "
        "limites do conjunto: dificuldade sem diversidade, custo ausente em 68 receitas e baixo silhouette "
        "dos clusters. Esses achados orientam uma nova coleta e revisão de rótulos."
    )]
    story += [p("6.1 Limitações e melhorias", "h2")]
    limitations = [
        ["Limitação", "Impacto", "Melhoria proposta"],
        ["Dificuldade possui uma única classe", "Impede avaliação supervisionada", "Coletar ou revisar rótulos variados"],
        ["Custo presente em apenas 52 receitas", "Teste pequeno e desbalanceado", "Ampliar amostra e usar validação cruzada"],
        ["PPMI não é Word2Vec", "Comparação não cobre o algoritmo solicitado", "Treinar Word2Vec com versão e semente fixas"],
        ["BERT ausente", "Sem representação contextual pré-treinada", "Adicionar modelo em português e registrar artefato"],
        ["Regras linguísticas rasas", "Relações ação-objeto contêm ruído", "Parser e NER supervisionados com revisão humana"],
    ]
    story += [table(limitations, [4.3 * cm, 5.0 * cm, 6.7 * cm])]

    story += [p("7. Conclusão", "h1")]
    story += [p(
        "TF-IDF foi a representação mais equilibrada: formou clusters tematicamente interpretáveis, "
        "produziu os melhores resultados qualitativos de busca e empatou com BoW na classificação de "
        "custo. O PPMI 32D apresentou maior silhouette e capturou contexto, mas introduziu falsos positivos "
        "na busca e teve menor F1 na classificação. BoW continua competitivo quando palavras explícitas "
        "são diretamente associadas ao alvo. A entrega demonstra que nenhuma métrica isolada basta: "
        "separação geométrica, coerência temática e utilidade no domínio devem ser avaliadas em conjunto."
    )]

    story += [p("8. Uso auxiliar de IA generativa", "h1")]
    disclosure = data["ai_disclosure"]
    disclosure_rows = [
        ["Fornecedor", disclosure["provider"]],
        ["Modelo", disclosure["model"]],
        ["Prompt utilizado", disclosure["prompt"]],
        ["Uso", disclosure["use"]],
    ]
    story += [table(disclosure_rows, [3.4 * cm, 12.6 * cm], header=False)]
    story += [p(
        "Contagens, métricas e rankings foram calculados localmente. A IA apoiou a redação e os scripts; "
        "autoria, interpretação e adequação às regras da disciplina exigem revisão humana.",
        "small",
    )]
    story += [p(
        "<b>9. Reprodutibilidade.</b> Os resultados estruturados estão em "
        "<font name='Courier'>output/results/resumo.json</font>. "
        "<font name='Courier'>analisar_resultados.py</font> recalcula as métricas e "
        "<font name='Courier'>gerar_relatorio.py</font> recria as figuras e o PDF.",
        "small",
    )]

    document.build(story, onFirstPage=header_footer, onLaterPages=header_footer)


def main() -> None:
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    FIGURES.mkdir(parents=True, exist_ok=True)
    draw_cluster_scatter(FIGURES / "clusters-tfidf.png", int(data["clustering"]["TF-IDF"]["run_id"]))
    classification = data["classification"]["representations"]
    draw_bar_chart(
        FIGURES / "comparacao-classificacao.png",
        "Classificação de custo por representação",
        ["BoW", "TF-IDF", "PPMI 32D"],
        [
            ("Acurácia", [classification[name]["accuracy"] for name in ("BoW", "TF-IDF", "PPMI-32D")], "#1763DC"),
            ("F1 macro", [classification[name]["macro_f1"] for name in ("BoW", "TF-IDF", "PPMI-32D")], "#00856F"),
        ],
        1.0,
        percent=True,
    )
    draw_linguistic_chart(FIGURES / "analise-linguistica.png", data["linguistic"])
    build_pdf(data)
    print(f"Relatório gravado em {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
