# syntax=docker/dockerfile:1
FROM node:24-bookworm-slim AS build
WORKDIR /build/frontend
COPY package.json package-lock.json ./
RUN npm ci
COPY src ./src
COPY index.html vite.config.ts tsconfig.json ./
RUN npm run build

FROM nginx:stable-alpine AS runtime
COPY nginx.conf /etc/nginx/nginx.conf
COPY --from=build /build/frontend/dist /usr/share/nginx/html
USER nginx
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=5 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
ENTRYPOINT ["nginx", "-g", "daemon off;"]
