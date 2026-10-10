# Build context is the repository root:
#   docker build -f apps/web/Dockerfile -t yearbook-web .
FROM node:26-slim AS build
ENV PNPM_HOME=/pnpm PATH=/pnpm:$PATH CI=true
RUN corepack enable && corepack prepare pnpm@10.34.6 --activate
WORKDIR /repo
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY packages/openapi/package.json packages/openapi/
COPY apps/web/package.json apps/web/
RUN pnpm install --frozen-lockfile
COPY packages/openapi packages/openapi
COPY apps/web apps/web
RUN pnpm --filter @yearbook/openapi generate && pnpm --filter @yearbook/web build

FROM node:26-slim AS runtime
ENV NODE_ENV=production PORT=3000 HOST=0.0.0.0
WORKDIR /app
COPY --from=build /repo/apps/web/.output ./.output
USER node
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=3s CMD node -e "fetch('http://127.0.0.1:3000/api/health').then(r=>process.exit(r.ok?0:1),()=>process.exit(1))"
CMD ["node", ".output/server/index.mjs"]
