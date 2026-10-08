FROM node:24-bookworm-slim AS build
WORKDIR /app
ARG APP_BASE=/
RUN npm install --global pnpm@11.4.0
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build --base="$APP_BASE"

FROM nginx:stable-alpine
COPY deploy/docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
