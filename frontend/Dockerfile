FROM node:20-bookworm AS build

WORKDIR /app

COPY frontend/package.json ./package.json

RUN npm install

COPY frontend/ ./

# Build-time API base URL. Leave empty (default) so the bundle uses same-origin
# requests through the nginx proxy. Override only when serving the static
# bundle directly without a proxy (e.g. `npm run dev`).
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
ARG GIT_COMMIT=""

COPY .git /tmp/.git
RUN export VITE_APP_GIT_COMMIT="${GIT_COMMIT:-$(git -C /tmp/.git rev-parse --short HEAD 2>/dev/null || true)}" && npm run build

FROM nginx:1.27-alpine

RUN apk add --no-cache openssl

COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
COPY frontend/docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 443

ENTRYPOINT ["/docker-entrypoint.sh"]