# Deskmate

Deskmate is a small desktop companion built with Python and PyQt6. It lives on your desktop as an animated floating pet and provides a lightweight chat bubble for LLM-powered conversations, reminders, weather, news, and local conversation history.

> This project is still under active development. Core features are usable locally, but the codebase and UI structure are still being refined.

## Preview

Screenshots and demo GIFs will be added once the UI stabilizes.

## Features

- Animated desktop pet with idle, sleeping, walking, and reminder states.
- Floating chat bubble UI instead of a traditional main window.
- LLM chat through an OpenAI-compatible Chat Completions endpoint.
- Local conversation history stored in SQLite.
- Weather lookup through a configurable weather API.
- News lookup through TianAPI, with numbered follow-up details.
- Reminder and todo support with APScheduler.
- Tray menu for quick access to chat, history, reminders, themes, and exit.
- Theme switching for user and assistant chat bubbles.

## Project Status

Deskmate is currently a personal desktop assistant prototype. The main interaction flow works, but the project is not yet packaged for end users.

Current focus:

- Stabilizing the floating bubble experience.
- Improving reminder and history workflows.
- Splitting the large UI file into smaller modules.
- Cleaning up documentation and setup instructions.

Not ready yet:

- One-click installer.
- Cross-platform packaging.
- Full test coverage.
- Polished onboarding flow.

## Requirements

- Python 3.9 or newer
- Windows is the primary development environment
- An OpenAI-compatible LLM endpoint
- API keys for optional weather and news features

Python dependencies are listed in [requirements.txt](requirements.txt).

## Quick Start

Clone the repository and install dependencies:

```powershell
py -m pip install -r requirements.txt
```

Create a local environment file:

```powershell
copy .env.example .env
```

Edit `.env` with your own service configuration:

```env
LLM_API_KEY=your-api-key
LLM_BASE_URL=https://your-openai-compatible-endpoint/v1
LLM_MODEL=your-model
LLM_REASONING_EFFORT=none
LLM_EXTRA_BODY=

TIANAPI_KEY=your-tianapi-key

WEA_API_KEY=your-weather-api-key
WEA_BASE_URL=https://api.weatherapi.com/v1
WEA_DEFAULT_CITY=天津
```

Run the app:

```powershell
py app.py
```

If `python` is available in your PATH, this also works:

```powershell
python app.py
```

## Configuration

Deskmate reads configuration from `.env`.

| Variable | Required | Description |
| --- | --- | --- |
| `LLM_API_KEY` | Yes | API key for the LLM service. |
| `LLM_BASE_URL` | Yes | OpenAI-compatible API base URL. |
| `LLM_MODEL` | Yes | Model name or model path used by the API. |
| `LLM_REASONING_EFFORT` | Optional | OpenAI-compatible reasoning control, for example `none`, `low`, `medium`, or `high` when supported by the endpoint. |
| `LLM_EXTRA_BODY` | Optional | JSON object merged into every chat request body for provider-specific switches, for example `{"enable_thinking": false}`. |
| `TIANAPI_KEY` | Optional | TianAPI key for news lookup. |
| `WEA_API_KEY` | Optional | Weather API key. |
| `WEA_BASE_URL` | Optional | Weather API base URL. |
| `WEA_DEFAULT_CITY` | Optional | Default city used for reminder weather tips. |

Weather and news features return friendly configuration messages when the related API keys are missing.

## Architecture

```text
app.py
  └─ src.ui.bubble_window.run_app()
       ├─ PyQt6 floating desktop UI
       ├─ ChatBackend
       │    ├─ Database
       │    ├─ IntentRouter
       │    └─ LLMEngine
       ├─ SessionService
       └─ ReminderService
            └─ ReminderScheduler
```

Main modules:

- [src/ui/bubble_window.py](src/ui/bubble_window.py): current floating UI implementation.
- [src/ui/cat_animation.py](src/ui/cat_animation.py): animation frame management.
- [src/core/chat_backend.py](src/core/chat_backend.py): chat orchestration.
- [src/core/intent_router.py](src/core/intent_router.py): intent routing and tool calling.
- [src/core/llm_engine.py](src/core/llm_engine.py): OpenAI-compatible LLM client.
- [src/core/database.py](src/core/database.py): SQLite persistence.
- [src/services/reminder_service.py](src/services/reminder_service.py): reminder business logic.
- [src/services/session_service.py](src/services/session_service.py): current session and history management.

## Data Storage

By default, local data is stored in:

```text
data/deskmate.db
```

The database currently contains:

- `sessions`: chat session metadata.
- `messages`: user and assistant messages.
- `reminders`: reminder records and status.

## Roadmap

- Split `src/ui/bubble_window.py` into smaller UI modules.
- Add screenshots and a short demo GIF.
- Improve first-run setup and missing-configuration guidance.
- Add basic tests for routing, reminders, and database operations.
- Add packaging instructions for Windows.
- Improve theme persistence.
- Add safer data migration support for future database changes.

## License

This project is released under the terms of the [MIT License](LICENSE).
