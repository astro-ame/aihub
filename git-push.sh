#!/usr/bin/env bash
# =============================================================
# git-push.sh — автоматизация commit + push в ветку master
# Использование:
#   ./git-push.sh "описание изменений"
#   ./git-push.sh  (без аргумента — откроет редактор)
# =============================================================

set -euo pipefail

BRANCH="master"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "$PROJECT_DIR"

# ── 1. Проверка: git инициализирован? ─────────────────────────
if ! git rev-parse --git-dir > /dev/null 2>&1; then
  echo "❌ Git не инициализирован. Запусти:"
  echo "   git init && git checkout -b master"
  exit 1
fi

# ── 2. Проверка: есть изменения? ──────────────────────────────
if git diff --quiet && git diff --cached --quiet && \
   [ -z "$(git ls-files --others --exclude-standard)" ]; then
  echo "ℹ️  Нет изменений для коммита."
  exit 0
fi

# ── 3. Показать статус ────────────────────────────────────────
echo ""
echo "📋 Изменения:"
git status --short
echo ""

# ── 4. Добавить все файлы ─────────────────────────────────────
git add -A

# ── 5. Сообщение коммита ──────────────────────────────────────
if [ -n "${1:-}" ]; then
  COMMIT_MSG="$1"
else
  # Автосообщение: дата + список изменённых файлов
  CHANGED=$(git diff --cached --name-only | head -5 | tr '\n' ', ' | sed 's/,$//')
  COUNT=$(git diff --cached --name-only | wc -l | tr -d ' ')
  COMMIT_MSG="update: ${CHANGED} (всего файлов: ${COUNT}) [$(date '+%Y-%m-%d %H:%M')]"
fi

# ── 6. Коммит ─────────────────────────────────────────────────
git commit -m "$COMMIT_MSG"
echo ""
echo "✅ Коммит создан: $COMMIT_MSG"

# ── 7. Push ───────────────────────────────────────────────────
if git remote get-url origin > /dev/null 2>&1; then
  echo "🚀 Отправка в origin/$BRANCH..."

  # Первый push (если ветка ещё не отслеживается)
  if git ls-remote --exit-code --heads origin "$BRANCH" > /dev/null 2>&1; then
    git push origin "$BRANCH"
  else
    git push -u origin "$BRANCH"
    echo "   (ветка $BRANCH создана на remote)"
  fi

  echo "✅ Push выполнен успешно."
else
  echo "⚠️  Remote origin не настроен. Push пропущен."
  echo "   Чтобы привязать репозиторий:"
  echo "   git remote add origin https://github.com/ВАШ_НИК/ВАШ_РЕПО.git"
  echo "   git push -u origin master"
fi
