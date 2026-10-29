# Trabalho da Unidade 3 - Processamento de Linguagem Natural

Esta pasta contém a entrega preenchida a partir do corpus de 120 receitas do projeto.
O relatório responde aos itens 1 a 6 do enunciado, registra as limitações e declara o
uso auxiliar de IA generativa.

## Conteúdo

- `analisar_resultados.py`: recalcula clustering, busca e classificação e consulta as
  análises linguísticas persistidas no SQLite;
- `gerar_relatorio.py`: cria as figuras e o PDF final;
- `output/results/resumo.json`: resultados estruturados e reproduzíveis;
- `output/figures/`: figuras usadas no relatório;
- `output/pdf/relatorio-unidade-3-preenchido.pdf`: documento final preenchido.

## Reprodução

Na raiz do repositório, execute:

```powershell
.\.venv\bin\python.exe trabalho-unidade-3\analisar_resultados.py
```

Para gerar o PDF, use um Python com `reportlab` e `Pillow`. No ambiente do Codex desta
entrega, essas bibliotecas pertencem ao runtime de documentos:

```powershell
& 'C:\Users\AMD\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' `
  trabalho-unidade-3\gerar_relatorio.py
```

Em outro ambiente, instale as dependências equivalentes antes do segundo comando:

```powershell
python -m pip install reportlab pillow
python trabalho-unidade-3\gerar_relatorio.py
```

Os scripts leem `data/recipes.sqlite`. A análise usa divisão estratificada determinística,
semente 42 e similaridade de cosseno.

## Escopo metodológico

O projeto possui uma representação densa local baseada em coocorrência, PPMI e projeção
determinística de 32 dimensões. Ela foi avaliada como alternativa densa, mas não foi
rotulada como Word2Vec. BERT não foi executado porque nenhum modelo Transformer faz parte
do ambiente reproduzível versionado.

Fornecedor/modelo de IA declarado no relatório: OpenAI, Codex (GPT-5). As métricas e os
rankings foram calculados localmente sobre o banco SQLite.
