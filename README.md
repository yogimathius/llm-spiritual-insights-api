# Perspective Loom

**Multi-Perspective LLM Dialogue Engine**

Perspective Loom is an exploratory Django API for structured conversations among configurable AI personas. Each role contributes a distinct perspective; the engine passes earlier responses into subsequent turns and can generate a final synthesis. A single-role workflow can also ask an LLM whether another configured role should collaborate.

The original 2024 experiment focused on questions of consciousness, meaning, and contemplative traditions. Those examples remain part of the project history; the underlying dialogue pattern is not limited to spiritual topics.

**Maturity:** Research prototype, last substantively updated in 2024. The code includes API implementations but has not been validated end-to-end for this rebrand. It is **not production-ready** and should not be presented as an autonomous multi-agent swarm or a benchmarked LLM platform.

## What the prototype explores

- **Role configuration:** persistent persona descriptions, prompt templates, collaboration preferences, and triggers.
- **Perspective chaining:** sequential dialogue and debate modes in which each role sees preceding responses.
- **Collaboration decisions:** an LLM-mediated choice to invite a second role for a single-role response.
- **Synthesis:** a separate language-model call summarizes agreements, differences, and insights.
- **Model backends:** GitHub Models through an OpenAI-compatible client and optional local Ollama.
- **HTTP API:** Django endpoints for asking a role, generating dialogue, streaming dialogue events, listing roles, and reading history.

The streamed endpoint emits newline-delimited dialogue events; it does not establish that token-by-token streaming is integrated or tested across the entire application.

## Prerequisites

- Python 3.12+
- Access to GitHub Models (for GITHUB_TOKEN)
- SQLite (configured by default)

## Frontend status

This repository contains the Django backend. Its original README referenced a separate React/Remix frontend at `yogimathius/frontend`, but that link is currently unavailable. Frontend operation has not been verified.

## Setup Instructions

1. Clone the repository:

```bash
git clone https://github.com/yogimathius/llm-spiritual-insights-api.git perspective-loom
cd perspective-loom
```

2. Create and activate virtual environment:

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Configure a GitHub Models token in your shell (or run a local Ollama model and set `use_ollama: true` in requests):

```bash
export GITHUB_TOKEN=your_github_models_token
```

The current code reads the token from the process environment; it does not automatically load a `.env` file.

5. Run database migrations:

```bash
python manage.py migrate
```

6. Initialize LLM roles and users:

Run the initialization script:

```bash
python manage.py initialize_llm_roles
```

Create a mock user:

```bash
python manage.py initialize_mock_user
```

7. Start the development server:

```bash
python manage.py runserver
```

## API Endpoints

### Ask Role

- **URL**: `/ai/ask-role/`
- **Method**: `POST`
- **Body**:

```json
{
  "prompt": "What does it mean when I dream of flying?",
  "role": "Quantum Philosopher"
}
```

- **Success Response**:

```json
{
  "response": [{ "role": "Quantum Philosopher", "response": "An example response..." }],
  "collaboration": null
}
```

- **Error Response**:

```json
{
  "error": "Missing prompt or role"
}
```

### List Roles

- **URL**: `/ai/roles/`
- **Method**: `GET`
- **Success Response**:

```json
{
  "roles": [
  {
    "name": "Quantum Philosopher",
    "description": "Explores reality through the lens of quantum mechanics and consciousness."
  }
  ]
}
```

## Frontend integration

The backend can be explored independently through its API endpoints. The original frontend reference is unavailable, so no working frontend is claimed here.

## Development

- The API uses Django's built-in development server
- SQLite database is used by default
- CORS is enabled for localhost frontend development
- Debug mode is enabled by default

## Security and verification notes

- **Do not deploy the current code publicly as-is.** The historical development settings enable Django DEBUG, use a checked-in development secret, and include CSRF-exempt endpoints.
- Conversation history is returned without an authentication guard in the current implementation. Add access control and data isolation before any public deployment.
- Automated tests have not been implemented in `ai_app/tests.py`; validate the API workflows with a reproducible test harness before promoting this beyond a research prototype.
- Never commit actual API tokens or an `.env` file. Use environment-scoped credentials with least privilege.
- Review the included historical text datasets for redistribution rights before bundling them into a release.

## Contributing

1. Fork the repository
2. Create your feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## Historical roadmap

The notes below were retained from the original exploratory development period. Unchecked items are aspirations, not claims about completed functionality.

## Next Steps

### 1. Randomize Full Dialogue Order

- [ ] Add randomization to role selection in DialogueGenerator
- [ ] Create method to shuffle roles while maintaining context
- [ ] Add option to specify "first speaker" roles
- [ ] Consider weighted randomization based on role relevance

### 2. Enhance Ollama Integration

- [ ] Add Ollama controls to frontend
  - [ ] Toggle for Ollama/OpenAI
  - [ ] Model selection dropdown
  - [ ] Streaming controls
- [ ] Implement streaming response handler
  - [ ] Add loading states for stream chunks
  - [ ] Show real-time token generation
  - [ ] Add stop/cancel functionality
- [ ] Model management
  - [ ] List available Ollama models
  - [ ] Show model status/availability
  - [ ] Model performance metrics

### 3. Context Enhancement with History

- [ ] Create conversation memory system
  - [ ] Define memory structure
  - [ ] Set memory limits
  - [ ] Implement cleanup strategies
- [ ] Add history retrieval features
  - [ ] Filter by role/topic
  - [ ] Search functionality
  - [ ] Relevance scoring
- [ ] Implement context injection
  - [ ] Add relevant history to prompts
  - [ ] Allow manual history selection
  - [ ] Create context window management

### Future Considerations

1. **Performance Optimization**

   - [ ] Caching frequently used contexts
   - [ ] Batch processing for history analysis
   - [ ] Efficient memory management

2. **User Experience**

   - [ ] Visual feedback during streaming
   - [ ] Progress indicators
   - [ ] Response quality metrics

3. **Advanced Features**
   - [ ] Role relationship mapping
   - [ ] Dynamic context weighting
   - [ ] Conversation branching

### Testing Strategy

- [ ] Unit tests for randomization
- [ ] Integration tests for streaming
- [ ] Performance tests for history retrieval
- [ ] End-to-end tests for full dialogue flow

### Documentation Needs

- [ ] API documentation updates
- [ ] Streaming implementation guide
- [ ] History integration examples
- [ ] Configuration options
