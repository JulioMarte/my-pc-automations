# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Etapa builder: instala devDependencies y compila TypeScript a dist/.
# ---------------------------------------------------------------------------
FROM node:24-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY tsconfig.json tsconfig.build.json ./
COPY src ./src
RUN npm run build

# ---------------------------------------------------------------------------
# Etapa runtime: imagen minima. Sin dependencias de runtime, no hace falta
# node_modules; solo dist/ y package.json (el codigo lee ../package.json para
# reportar la version).
# ---------------------------------------------------------------------------
FROM node:24-alpine AS runtime

# tini como PID 1: reapea procesos zombie y propaga SIGINT/SIGTERM a node.
RUN apk add --no-cache tini

WORKDIR /app
ENV NODE_ENV=production

# Copia el artefacto compilado y los scripts de arranque/salud con dueño node.
COPY --from=builder --chown=node:node /app/dist ./dist
COPY --chown=node:node package.json ./
COPY --chown=node:node scripts/docker-entrypoint.sh scripts/docker-healthcheck.sh ./scripts/
RUN chmod +x ./scripts/docker-entrypoint.sh ./scripts/docker-healthcheck.sh \
    && mkdir -p /app/logs && chown -R node:node /app

# Usuario sin privilegios (ya existe en la imagen oficial node:24-alpine).
USER node

EXPOSE 8888 1080 8899

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["/app/scripts/docker-healthcheck.sh"]

ENTRYPOINT ["/sbin/tini", "--", "/app/scripts/docker-entrypoint.sh"]
