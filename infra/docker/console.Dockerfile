# The dashboard (ADR-0026, ADR-0079): Next.js, built standalone.
#
#   docker build -f infra/docker/console.Dockerfile \
#     --build-arg API_BASE_URL=https://api.fiveneurals.com -t neura-console .
#
# API_BASE_URL is needed at BUILD time: Next bakes the `/api/*` rewrite into the
# build (next.config.ts). The server pages read it again at run time.
FROM node:22-slim AS build
WORKDIR /app
COPY apps/neura-console/package.json apps/neura-console/package-lock.json ./
RUN npm ci
COPY apps/neura-console/ ./
ARG API_BASE_URL
ENV API_BASE_URL=$API_BASE_URL NEXT_OUTPUT=standalone NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-slim
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
USER node
EXPOSE 3000
CMD ["node", "server.js"]
