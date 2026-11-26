# Panela Aberta

Interface inicial do chatbot de receitas por ingredientes, preparada para Cloudflare Pages e Pages Functions.

## Executar localmente

```bash
npm install
npm run dev
```

O Wrangler publica os arquivos de `public/` e mapeia `functions/api/chat.js` para `POST /api/chat`.

## Publicar

O caminho mais simples é conectar o repositório a um projeto Cloudflare Pages e definir `chatbot-web` como diretório raiz. Também é possível publicar com:

```bash
npm run deploy
```

Ao adicionar uma API nutricional, guarde a chave como segredo, nunca em `public/`:

```bash
npx wrangler pages secret put USDA_API_KEY --project-name panela-aberta-chatbot
```

Para desenvolvimento local, crie `chatbot-web/.dev.vars`:

```text
USDA_API_KEY=sua_chave
```

Esse arquivo é ignorado pelo Git.

## Estado atual

- interface responsiva e acessível;
- mensagens rápidas e nova conversa;
- endpoint demonstrativo com ranking por cobertura de ingredientes;
- fallback local para visualizar a interface sem o Wrangler;
- nenhum valor nutricional fictício;
- próximo passo: substituir o pequeno catálogo demonstrativo pelas receitas armazenadas no banco do projeto.
