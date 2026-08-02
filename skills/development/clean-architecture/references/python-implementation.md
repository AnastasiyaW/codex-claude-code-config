# Clean Architecture in Python — Operational Knowledge (Part 1: Layers, Core Components, Basic Build)

> Distilled from chapters 1–3 of Leonardo Giordani, *Clean Architectures in Python* (2nd ed.).
> Rewritten as operational guidance for a coding agent implementing clean architecture in Python.
> Scope of this part: the layer model, dependency rules, entities, use cases, repositories,
> serializers, and the TDD flow used to build them. Error handling / request-response objects,
> web layer, and real database integration are covered in later parts (book chapters 4–8).

---

## 0. Mindset: it's a methodology, not a law

- Clean architecture is a **set of design guidelines**, not a checklist to apply blindly. Adopt a
  rule only when you can articulate the problem it solves for *this* project.
- The architecture trades **more abstraction layers and upfront effort** for replaceability and
  testability. On tiny scripts or hot performance paths this trade may not pay off — it is
  legitimate to break the rules, but every deliberate break must be **documented loudly**
  (comment + design note) so a future maintainer knows the violation is intentional, not a bug.
- The single question the architecture answers at all times: **"what is where and why."** If you
  cannot answer that for a piece of code, its placement is wrong.
- If you find yourself breaking the same layer boundary repeatedly, don't keep patching — that is
  a signal the two layers should be merged (one abstraction level too many for this system).

## 1. The layer model

Four concentric layers, from innermost (most abstract, most stable) to outermost (most concrete,
most replaceable):

```
+---------------------------------------------------------------+
|  External systems   (web framework, CLI, DB engine, msg bus)  |
|  +---------------------------------------------------------+  |
|  |  Gateways / interfaces  (repository interface, adapters) |  |
|  |  +---------------------------------------------------+  |  |
|  |  |  Use cases  (application-specific business logic)  |  |  |
|  |  |  +---------------------------------------------+  |  |  |
|  |  |  |  Entities  (domain models, business vocab)  |  |  |  |
|  |  |  +---------------------------------------------+  |  |  |
|  |  +---------------------------------------------------+  |  |
|  +---------------------------------------------------------+  |
+---------------------------------------------------------------+
```

| Layer | Contains | Knows about | Never touches |
|---|---|---|---|
| **Entities** | Lightweight domain models (dataclasses/plain classes) | Other entities only | DB, ORM, HTTP, JSON, use cases, frameworks |
| **Use cases** | One business process each; orchestration of entities + gateways | Entities; gateway *interfaces*; other use cases | Concrete DB drivers, web framework objects, HTTP details |
| **Gateways** | Interfaces/adapters that wrap external services in an app-tailored API | Entities, use cases (rarely calls them) | — (they exist to hide the outer layer's details) |
| **External systems** | Web framework, CLI script, actual DB repository implementation, message bus | Everything inward (gateways, use cases, entities) | — (outermost) |

Key vocabulary:

- **Business logic** — the data transformation that is the reason your system exists. It lives in
  use cases (process) and entities (vocabulary). Everything else is delivery/storage machinery.
- **Implementation detail** — any component not central to the design: the web framework, the
  database, the serialization format. "Detail" is a **topological** term, not a complexity
  ranking — a relational DB is vastly more complex than a sort routine, yet it is still a detail
  because replacing it must not touch the core.
- **"Lower/higher" = abstraction level**, not importance. Inner layers are more abstract.

### 1.1 The dependency rules (the part you must never get wrong)

1. **Source-code dependencies point inward only.** An entity imports nothing from use cases;
   a use case imports nothing from Flask/SQLAlchemy/psycopg; gateway interfaces import entities,
   never the concrete driver.
2. **Same-layer communication is unrestricted.** Entities may instantiate and call other entities
   directly; use cases may compose other use cases.
3. **The Golden Rule: talk inward with plain data, talk outward through interfaces.**
   - *Inward* calls (web handler → use case, use case → entity) pass **simple structures**:
     entities, dicts, primitives — things defined in inner layers or by the language itself.
   - *Outward* calls (use case → storage) go **only through an interface** the inner layer
     defines/expects; the concrete implementation is injected from outside at wiring time.
4. **Direction asymmetry, concretely:**
   - Web framework calling a use case = **inward** → direct call is fine, no interface needed
     (outer layers have full access to inner ones).
   - Use case reading from storage = **outward** → must go through the repository interface;
     the use case never knows whether behind it sits Postgres, Mongo, a text file, or a dict.
5. **Types flow with dependencies.** Shared data types are a form of coupling; whoever is inner
   defines the types, outer layers adapt to them. The entities layer is "the vocabulary of the
   business" — repositories return entities, use cases return entities, and the outermost layer
   converts entities into HTTP/JSON/CLI output at the boundary.
6. **Breaking the data flow invalidates the architecture.** If a use case reaches directly into a
   DB driver for performance, that is the one class of violation you must escalate: allowed only
   with an explicit, visible warning in code and docs, and repeated violations mean the layer
   should be removed.

### 1.2 Inversion of control — how the decoupling actually happens

Two moves, in this order:

1. **Wrap the callee** (e.g., the database) behind a standard interface — a small set of methods
   named in business terms (e.g., `list_rooms_with_status(status)`), each translating to whatever
   the wrapped technology needs (SQL, HTTP, file reads).
2. **Modify the caller** (the use case) so it never names the concrete implementation: it accepts
   the dependency as a parameter (constructor arg or function arg) and calls only the interface
   methods. The concrete adapter is instantiated at the outermost edge (the CLI script, the app
   factory) and injected.

Python specifics: there is no `interface` keyword — an "interface" is simply the set of methods
the inner code calls on the injected object (duck typing). You *may* formalize it with `abc.ABC`
or `typing.Protocol`, but the book's baseline approach is: document the expected methods via the
tests that mock them, and trust duck typing. Mocks in tests double as the interface's executable
specification.

### 1.3 Why bother (the payoffs to check your design against)

- **Swap tests:** could you replace the web UI with a CLI, or Postgres with flat files, by
  writing only new outer-layer code? If yes, the layering is right. The shape of the system and
  its data flow must not change when a detail changes.
- **Testability:** every layer can be detached and tested in isolation because its inputs and
  outputs are explicit. You test the web layer with a fake use case; you test the use case with a
  mocked repository; entities need no doubles at all.
- **Clarity of responsibility:** components must be forbidden from doing anything not assigned to
  them at design time; overlapping areas of control breed bugs and deadlocks. Divide et impera.

## 2. Request lifecycle through a clean system (canonical data flow)

For a query like `GET /rooms?status=available`:

1. **Web framework** (external layer) parses HTTP: extracts endpoint + query params. Its whole
   domain is the HTTP protocol — no business decisions here.
2. It calls the **use case** (inward, direct call), passing plain parameters.
3. The use case executes the **business logic**: asks the injected **repository interface** for
   the data (outward, through the interface), applies whatever filtering/ordering/composition the
   business requires.
4. The **adapter** behind the interface translates the call into technology-specific operations
   (SQL, file IO, network) and translates results **back into domain entities**.
5. The use case returns entities/plain structures to the web framework.
6. The web framework serializes to the delivery format (HTML page, JSON body) and builds the
   HTTP response.

Every hop is a data-format translation at a boundary. That translation cost is deliberate: shared
common formats at the boundaries are what buys loose coupling.

## 3. Concrete Python implementation patterns

Reference project shape (a room-rental search service, "one package per layer"):

```
project/
├── cli.py                        # external system: composition root + delivery
├── src_pkg/
│   ├── domain/
│   │   └── room.py               # entities
│   ├── use_cases/
│   │   └── room_list.py          # use cases
│   ├── serializers/
│   │   └── room.py               # boundary format converters
│   └── repository/
│       └── memrepo.py            # external-system implementations of the storage interface
└── tests/
    ├── domain/test_room.py       # mirror the package tree; __init__.py in every test subdir
    ├── use_cases/test_room_list.py
    ├── serializers/test_room.py
    └── repository/test_memrepo.py
```

### 3.1 Entities — lightweight domain models

Rules:

- Entities are **plain data + domain behavior**. They are NOT Django/SQLAlchemy models: no
  `.save()`, no `.objects.filter()`, no JSON methods wired to a presentation layer, no DB session.
- Only create an entity when the concept is complex enough to deserve one. Don't wrap what the
  language already models well (a `str` is fine as a `str` unless your domain analyzes text
  structure).
- `dataclasses` are the idiomatic compact implementation: free `__init__`, `__eq__` (needed for
  test assertions and value comparison), `asdict`.
- Give entities **boundary helpers** for the data shapes other layers will hand you — typically
  dicts:

```python
# domain/room.py
import dataclasses
import uuid


@dataclasses.dataclass
class Room:
    code: uuid.UUID
    size: int
    price: int
    longitude: float
    latitude: float

    @classmethod
    def from_dict(cls, d):
        return cls(**d)

    def to_dict(self):
        return dataclasses.asdict(self)
```

- `from_dict` exists because outer layers (HTTP forms, DB rows, config) naturally produce dicts.
- `to_dict` is a **structure conversion, not serialization** — the result is still Python data,
  not a string. String encoding is a separate, outer concern (see serializers).
- Equality by value (`__eq__`) matters: tests and use cases compare entity instances directly.

### 3.2 Serializers — boundary encoders, separate from the model

- A serializer is a **specialized external class** that knows how to render an entity in a wire
  format (JSON, etc.). It must not live on the entity: the entity would otherwise be coupled to a
  presentation concern.
- Idiomatic JSON approach — subclass `json.JSONEncoder`:

```python
# serializers/room.py
import json


class RoomJsonEncoder(json.JSONEncoder):
    def default(self, o):
        try:
            return {
                "code": str(o.code),      # UUID is not JSON-native → encode here
                "size": o.size,
                "price": o.price,
                "latitude": o.latitude,
                "longitude": o.longitude,
            }
        except AttributeError:  # pragma: no cover
            return super().default(o)
```

Usage: `json.dumps(room, cls=RoomJsonEncoder)`.

- Note the division of labor: `to_dict()` can't be reused blindly because some field types (UUID)
  are not JSON-serializable — the encoder is exactly the place where such type adaptations live.
  A little duplication between `to_dict` and the encoder is acceptable *because both are covered
  by tests*.
- Test trick: compare JSON by `json.loads(actual) == json.loads(expected)` — dict comparison
  ignores key order, string comparison doesn't.

### 3.3 Use cases — the business process

- **One use case = one small, isolated business action** (list rooms, log in a user, execute a
  payment). Small use cases are easier to test, understand, and compose; complex use cases should
  be built by composing simple ones.
- **Function vs class:** default to a plain function — a use case is a process (inputs → outputs),
  and a function is the simplest encoding of that. Reach for a class only when the process needs
  real structure (multiple injected systems, staged initialization, shared helpers). The author
  explicitly calls his first-edition class-based use cases a mistake for the simple case.
- The repository (and any other external service) arrives **as an argument**:

```python
# use_cases/room_list.py
def room_list_use_case(repo):
    return repo.list()
```

- Yes, at this stage it's a one-line wrapper. That's correct and expected: the value is the seam.
  Error handling, request validation, and filtering are added later *inside this seam* without
  the callers changing shape (book chapter 5 introduces request/response objects for that).
- Use cases have full access to entities (may instantiate/manipulate them directly) and may call
  other use cases. They receive and return **domain-level data** (entities, primitives), never
  framework objects.

### 3.4 Repositories — the storage gateway

- "Repository" = the object the use case queries for data. Its abstraction level is **higher than
  an ORM's**: it exposes only the operations the application needs, named for the business
  problem (`list`, `list_rooms_with_status`), not generic query machinery. SQLAlchemy/psycopg may
  be *inside* the implementation; they are never the interface.
- A repository **returns domain entities**, not rows/dicts/ORM objects. The conversion happens
  inside the repository (it's in an outer layer, so it may freely import and build entities).
- Baseline implementation for development and tests — an in-memory repo:

```python
# repository/memrepo.py
from src_pkg.domain.room import Room


class MemRepo:
    def __init__(self, data):          # data: list of dicts
        self.data = data

    def list(self):
        return [Room.from_dict(row) for row in self.data]
```

- This class is a stand-in with the **exact same public API** a Postgres/Mongo/file-based
  implementation will have. Because the use case only ever sees `.list()`, swapping the engine
  is a pure outer-layer change (proved in later book chapters).
- The in-memory repo needs data loaded at construction only because it has no persistence — a
  real DB-backed repo would connect instead. Don't mistake the hardcoded seed data for an
  architectural feature.

### 3.5 The composition root — wiring at the outermost edge

The one place where concrete implementations meet: an entry-point script (CLI here; an app
factory for web apps). Pattern: **instantiate adapters → run use case with them injected →
convert results for the audience**.

```python
#!/usr/bin/env python
# cli.py
from src_pkg.repository.memrepo import MemRepo
from src_pkg.use_cases.room_list import room_list_use_case

rooms = [
    {"code": "a1b2...", "size": 215, "price": 39,
     "longitude": -0.09998975, "latitude": 51.75436293},
    # ...
]

repo = MemRepo(rooms)
result = room_list_use_case(repo)
print([room.to_dict() for room in result])
```

- This file is the **only** place that knows both the concrete repo class and the use case.
- Presentation conversion (`to_dict` before printing) happens here, at the boundary — printing
  raw entities would show useless object reprs.
- Adding a web UI later = writing a second composition root + delivery layer; zero changes to
  domain/use_cases/repository.

## 4. TDD workflow for building these components

The book builds every component test-first. The rhythm, per component:

1. **Write the test first** — it documents the public API you wish existed.
2. **Run the suite; confirm the new test fails** (a test that never failed proves nothing).
3. **Write the minimal implementation** that makes it pass.
4. **Run the full suite green** before moving on. Running `pytest -svv` after every step is
   assumed background workflow, not a special event. Add `--cov=<pkg> --cov-report=term-missing`
   when you care about coverage.

Component-specific testing rules:

- **Entities:** test construction with correct values, `from_dict`, `to_dict` round-trip, and
  equality of two instances built from the same data. No mocks needed anywhere.
- **Serializers:** build an entity, `json.dumps` with the encoder, compare via parsed dicts.
- **Use cases:** the repository is an *outward* dependency → **mock it**:

```python
# tests/use_cases/test_room_list.py
from unittest import mock
import pytest

from src_pkg.domain.room import Room
from src_pkg.use_cases.room_list import room_list_use_case


@pytest.fixture
def domain_rooms():
    return [Room(code=..., size=215, price=39,
                 longitude=-0.09998975, latitude=51.75436293),
            # a few more...
            ]


def test_room_list_without_parameters(domain_rooms):
    repo = mock.Mock()
    repo.list.return_value = domain_rooms

    result = room_list_use_case(repo)

    repo.list.assert_called_with()          # HOW the outgoing query was made
    assert result == domain_rooms           # correctness of the returned data
```

  Unit-testing doctrine applied here: you don't test the outgoing query's *behavior* (that's the
  repository's own test suite's job) — you test **that your code issues the query with the right
  parameters** (`assert_called_with`) and handles the returned data correctly.
- **Repositories:** test the concrete class against its public API directly — feed known dicts,
  assert the returned value is the expected list of *entities* (`repo.list() == [Room.from_dict(d)
  for d in dicts]`). This test doubles as the executable spec of the storage interface.
- **Web/delivery layer** (preview of later chapters): test with a **fake use case** — assert the
  handler calls the use case with the right parameters and converts its return into the right
  HTTP response. No storage, no business logic involved.
- Use pytest **fixtures** for shared test data (lists of entities/dicts); mirror the source tree
  under `tests/`, adding `__init__.py` to each test subdirectory.

The composite picture: **mocks point outward** (mock what the component under test calls through
an interface), **real objects point inward** (entities are cheap and pure — always use them for
real in any layer's tests).

## 5. Actionable rules (checklist)

1. Dependencies point inward only; verify by reading imports: `domain/` imports stdlib only;
   `use_cases/` imports `domain` (+ stdlib); `repository/`, `serializers/`, delivery code may
   import anything inward.
2. Inward calls pass plain data/entities; outward calls go through injected interfaces.
3. Entities: dataclasses with `from_dict` / `to_dict` / value equality; zero persistence or
   presentation knowledge.
4. Serialization lives outside the model, in encoder classes; handle non-JSON-native types there.
5. One use case per business action; plain functions by default; dependencies as arguments.
6. Repository API is business-tailored and minimal; it returns entities, not rows; ORMs are an
   internal detail of one implementation.
7. Wire concrete implementations only at the composition root (CLI script / app factory).
8. Build test-first; mock outward dependencies, use real entities; assert both call parameters
   (outgoing) and returned data.
9. Test files mirror source layout; run the whole suite after every change.
10. Any deliberate rule break (e.g., use case → raw DB for performance) gets a loud comment and a
    design-doc entry naming the reason; recurring breaks of the same boundary → merge the layers.

## 6. Anti-patterns

- **Business logic in the delivery layer** — filtering/sorting/decisions inside the Flask view or
  CLI arg parser. The framework's domain is its protocol; move the logic into a use case.
- **Fat framework models as domain models** — Django/SQLAlchemy models used as entities couple
  the core to storage. Entities must be constructible and testable with nothing installed.
- **Use case importing a driver** — `import psycopg` (or `sqlalchemy`, `pymongo`) anywhere in
  `use_cases/` means a DB change forces business-logic changes. Inject a repository instead.
- **Repository leaking its technology** — returning ORM objects, cursors, or raw rows to the use
  case; or exposing generic query builders as its API. Return entities via a business-named API.
- **Serialization methods on entities** (e.g., `room.to_json()`) — couples the core vocabulary to
  one wire format.
- **Class-shaped use cases with no state** — ceremony without benefit; a function does it.
- **Bidirectional type dependencies** — an inner layer consuming types defined by an outer layer
  (the "shop dictating item sizes to the wholesaler" inversion). Whoever is inner defines the
  shared types.
- **Silent data-flow violations** — an undocumented shortcut across layers is a landmine for
  whoever later swaps the outer component. Document or don't do it.
- **Testing outgoing query results instead of parameters** in use-case tests — duplicates the
  repository's tests and welds the mock to implementation details.
- **Treating "detail" as "unimportant/simple"** — details (DB, framework) can be the most complex
  parts; the term only means "replaceable without touching the core."
- **Applying the full layer stack to everything** — for a throwaway script the abstraction tax
  may exceed the payoff; the architecture is justified by expected change and testing needs.

## 7. Glossary (as used in this material)

- **Entity / domain model** — lightweight class encoding a business concept; inner layer.
- **Use case** — one application-specific business process; orchestrates entities and gateways.
- **Gateway / repository** — interface (and its adapters) wrapping an external service in an
  application-tailored API; "repository" is the storage-flavored gateway.
- **External system** — anything peripheral to business logic: web framework, DB engine, CLI,
  message bus — including in-house code ("external" is topological, not organizational).
- **Inversion of control** — depending on an interface and receiving the concrete implementation
  from outside, instead of naming it directly.
- **Golden Rule** — inward with simple structures, outward through interfaces.
- **Composition root** — the outermost wiring point where concrete adapters are instantiated and
  injected into use cases.

# Clean Architecture in Python — Practical Patterns (Part 2)
## Web adapters, error management, real-database integration

Distilled operational notes covering three concerns: attaching a web framework as an
outer-layer detail, a request/response error-management architecture for use cases, and
integrating a real Postgres repository with a Docker-based integration-test harness.
All code below is fresh illustrative material, not book text.

---

## 1. The web framework is a delivery detail, not the application

### 1.1 Core idea

The HTTP layer (Flask, FastAPI, Django views — the choice is irrelevant) lives in the
**outermost ring**. It is a *gateway*: a thin translator between the HTTP protocol and
your use cases. The proof of a correctly layered system is that a CLI script and a web
endpoint invoke the use case with **identical code** — only the presentation of the
result differs. If adding an HTTP interface forces changes inside `use_cases/` or
`domain/`, the dependency arrows are pointing the wrong way.

Consequences you can act on:

- The web app gets its **own package** (e.g. `application/`) separate from the core
  package (e.g. `myapp/` with `domain/`, `use_cases/`, `repository/`, `requests/`,
  `responses/`, `serializers/`). The core package never imports from `application/`.
- REST/JSON conventions are *also* not part of the architecture — they are a choice made
  entirely inside the gateway layer.
- Skip the framework's ORM/database machinery entirely; the repository layer already owns
  persistence. Use the framework only for routing, request parsing, and response emission.

### 1.2 Minimal wiring (Flask as the example)

Three small pieces:

**Config as plain classes** — one class per environment, selected by name at startup:

```python
# application/config.py
class Config:
    """Shared base config."""

class ProductionConfig(Config):
    pass

class DevelopmentConfig(Config):
    pass

class TestingConfig(Config):
    TESTING = True
```

**App factory** — a function that builds and returns the app; never a module-level
singleton. The factory pattern is what makes the app testable (tests build their own
instance with the testing config) and lets one codebase serve dev/test/prod:

```python
# application/app.py
from flask import Flask
from application.rest import room

def create_app(config_name: str) -> Flask:
    app = Flask(__name__)
    app.config.from_object(f"application.config.{config_name.capitalize()}Config")
    app.register_blueprint(room.blueprint)
    return app
```

**WSGI entry point** — the only place that touches the process environment:

```python
# wsgi.py
import os
from application.app import create_app

app = create_app(os.environ["FLASK_CONFIG"])
```

Run with `FLASK_CONFIG="development" flask run`.

### 1.3 The endpoint = composition root

Dependency injection here is **manual and explicit**: the endpoint function constructs
the repository, builds the request object, calls the use case as a plain function, and
serializes the response. No DI container needed — the use case receives its dependencies
as arguments (`use_case(repo, request)`), which is the whole inversion.

```python
# application/rest/room.py
import json
from flask import Blueprint, Response, request

from myapp.repository.memrepo import MemRepo
from myapp.use_cases.room_list import room_list_use_case
from myapp.requests.room_list import build_room_list_request
from myapp.responses import ResponseTypes
from myapp.serializers.room import RoomJsonEncoder

blueprint = Blueprint("room", __name__)

HTTP_STATUS = {
    ResponseTypes.SUCCESS: 200,
    ResponseTypes.RESOURCE_ERROR: 404,
    ResponseTypes.PARAMETERS_ERROR: 400,
    ResponseTypes.SYSTEM_ERROR: 500,
}

@blueprint.route("/rooms", methods=["GET"])
def room_list():
    # 1. translate HTTP query string -> use-case request
    filters = {
        key.removeprefix("filter_"): value
        for key, value in request.args.items()
        if key.startswith("filter_")
    }
    request_object = build_room_list_request(filters=filters)

    # 2. wire dependencies and execute
    repo = MemRepo(seed_data)          # swap for PostgresRepo(config) later
    response = room_list_use_case(repo, request_object)

    # 3. translate use-case response -> HTTP response
    return Response(
        json.dumps(response.value, cls=RoomJsonEncoder),
        mimetype="application/json",
        status=HTTP_STATUS[response.type],
    )
```

Naming gotcha: inside a Flask view, `request` is the framework's HTTP request. Call your
use-case input `request_object` (or similar) to avoid shadowing — same collision happens
in tests where `pytest-flask` provides a `request`-adjacent fixture ecosystem.

### 1.4 Testing the gateway

The endpoint is tested with the **use case mocked out** — the use case has its own tests;
the gateway test only verifies translation logic in both directions:

```python
# tests/rest/test_room.py
import json
from unittest import mock
import pytest
from myapp.responses import ResponseSuccess, ResponseFailure, ResponseTypes

@mock.patch("application.rest.room.room_list_use_case")
def test_get(mock_use_case, client):
    mock_use_case.return_value = ResponseSuccess(some_domain_rooms)

    http_response = client.get("/rooms")

    assert http_response.status_code == 200
    assert http_response.mimetype == "application/json"
    # inbound translation: use case received a request with empty filters
    args, kwargs = mock_use_case.call_args
    assert args[1].filters == {}

@mock.patch("application.rest.room.room_list_use_case")
def test_get_with_filters(mock_use_case, client):
    mock_use_case.return_value = ResponseSuccess(some_domain_rooms)
    client.get("/rooms?filter_price__gt=2&filter_price__lt=6")
    args, _ = mock_use_case.call_args
    # NB: query-string values arrive as strings
    assert args[1].filters == {"price__gt": "2", "price__lt": "6"}

@pytest.mark.parametrize("rtype,status", [
    (ResponseTypes.PARAMETERS_ERROR, 400),
    (ResponseTypes.RESOURCE_ERROR, 404),
    (ResponseTypes.SYSTEM_ERROR, 500),
])
@mock.patch("application.rest.room.room_list_use_case")
def test_failures_map_to_http_status(mock_use_case, client, rtype, status):
    mock_use_case.return_value = ResponseFailure(rtype, "boom")
    assert client.get("/rooms").status_code == status
```

Fixture setup: `pytest-flask` auto-provides `client` but expects you to define an `app`
fixture (in `tests/conftest.py`) that calls your factory with the testing config:

```python
# tests/conftest.py
import pytest
from application.app import create_app

@pytest.fixture
def app():
    return create_app("testing")
```

What to assert in gateway tests: status code, MIME type, JSON body shape, that the use
case was called, and **the exact request object contents** (via `mock.call_args`, since
request objects usually lack `__eq__`).

---

## 2. Error management: request objects, response objects, error types

### 2.1 Why dedicated transport objects

Use cases are the main execution path, hence the main error source. Instead of letting
exceptions and raw dicts leak across layer boundaries, define two families of transport
objects:

- **Request objects** — carry validated input *into* a use case. Built from whatever the
  outside world provides (query strings, CLI args, message payloads). They absorb the
  entire "garbage input" problem class: wrong types, unknown keys, missing params.
- **Response objects** — carry results *out of* a use case, with a uniform structure that
  can express both success and every category of failure.

These are **not** HTTP requests/responses. They are internal to the application and exist
even for a CLI. The architecture prescribes their existence, not their implementation —
plain classes work fine.

### 2.2 Requests: validate before the use case, factory returns valid OR invalid

Key design decision: validation happens **at construction time**, outside the use case.
A builder/factory function returns one of two types — a valid request or an invalid one
carrying a list of errors. Both are truthy-testable, so the use case needs exactly one
check: `if not request: ...`.

```python
# myapp/requests/room_list.py
from collections.abc import Mapping

class RoomListInvalidRequest:
    def __init__(self):
        self.errors = []

    def add_error(self, parameter, message):
        self.errors.append({"parameter": parameter, "message": message})

    def has_errors(self):
        return len(self.errors) > 0

    def __bool__(self):
        return False

class RoomListValidRequest:
    def __init__(self, filters=None):
        self.filters = filters

    def __bool__(self):
        return True

ACCEPTED_FILTERS = {"code__eq", "price__eq", "price__lt", "price__gt"}

def build_room_list_request(filters=None):
    invalid = RoomListInvalidRequest()

    if filters is not None:
        if not isinstance(filters, Mapping):
            invalid.add_error("filters", "Is not iterable")
            return invalid
        for key in filters:
            if key not in ACCEPTED_FILTERS:
                invalid.add_error("filters", f"Key {key} cannot be used")
    if invalid.has_errors():
        return invalid
    return RoomListValidRequest(filters=filters)
```

Points that matter:

- Requests are **per-use-case** (each use case knows what input it accepts); an explicit
  whitelist of accepted filter keys/operators keeps arbitrary input from reaching the
  storage layer.
- Collect **all** errors, not just the first, so the caller gets a complete diagnosis in
  one round trip (each error = `{parameter, message}`).
- `__bool__` is the contract: valid → `True`, invalid → `False`. Cheap, uniform, and
  makes the use-case guard a one-liner.
- Type-check against abstract types (`collections.abc.Mapping`) rather than `dict`.

### 2.3 Responses: one success type, one failure type, a small error taxonomy

```python
# myapp/responses.py
class ResponseTypes:
    SUCCESS = "Success"
    PARAMETERS_ERROR = "ParametersError"
    RESOURCE_ERROR = "ResourceError"
    SYSTEM_ERROR = "SystemError"

class ResponseSuccess:
    def __init__(self, value=None):
        self.type = ResponseTypes.SUCCESS
        self.value = value

    def __bool__(self):
        return True

class ResponseFailure:
    def __init__(self, type_, message):
        self.type = type_
        self.message = self._format_message(message)

    def _format_message(self, msg):
        # accept either a plain string or an Exception instance
        if isinstance(msg, Exception):
            return f"{msg.__class__.__name__}: {msg}"
        return msg

    @property
    def value(self):
        return {"type": self.type, "message": self.message}

    def __bool__(self):
        return False

def build_response_from_invalid_request(invalid_request):
    message = "\n".join(
        f"{err['parameter']}: {err['message']}" for err in invalid_request.errors
    )
    return ResponseFailure(ResponseTypes.PARAMETERS_ERROR, message)
```

The **three failure categories** (deliberately parallel to HTTP semantics, which makes
the gateway mapping trivial):

| Type | Meaning | Typical HTTP mapping |
|---|---|---|
| `PARAMETERS_ERROR` | Input to the use case was malformed/invalid | 400 |
| `RESOURCE_ERROR` | Process ran fine but the requested thing doesn't exist | 404 |
| `SYSTEM_ERROR` | The process itself broke (unexpected exception, external system failure) | 500 |

Extend the taxonomy when you need finer granularity, but these three cover the base
cases of any use case. The mapping table lives **in the gateway** (section 1.3), not in
the responses module — HTTP codes are a delivery concern.

`_format_message` accepting exceptions is a small but load-bearing convenience: external
libraries raise exceptions you can't (or won't) enumerate; wrapping them as
`"ExceptionClass: text"` gives a serializable, loggable failure without letting the
exception itself cross the boundary.

`ResponseFailure.value` returning `{"type", "message"}` means the gateway can serialize
`response.value` unconditionally — success payload and failure payload go through the
same code path.

### 2.4 The canonical use-case shape

With requests and responses in place, every use case follows one template:

```python
# myapp/use_cases/room_list.py
from myapp.responses import (
    ResponseSuccess, ResponseFailure, ResponseTypes,
    build_response_from_invalid_request,
)

def room_list_use_case(repo, request):
    if not request:                       # invalid request -> parameters error
        return build_response_from_invalid_request(request)
    try:
        rooms = repo.list(filters=request.filters)
        return ResponseSuccess(rooms)
    except Exception as exc:              # anything below blew up -> system error
        return ResponseFailure(ResponseTypes.SYSTEM_ERROR, exc)
```

Rules encoded here:

1. **A use case never raises** across its boundary. It always returns a response object
   with a known shape. Callers branch on `bool(response)` / `response.type`, never on
   exception types.
2. First statement: validity guard. Validation logic itself lives in the request builder;
   the use case only *checks* validity.
3. The broad `except Exception` at the use-case boundary is intentional — it converts
   unknown failures from repositories/external systems into `SYSTEM_ERROR` instead of a
   500-with-stack-trace. (Log the exception here in real systems.)
4. Business-rule failures you *can* anticipate return `RESOURCE_ERROR` /
   domain-appropriate failures explicitly rather than falling into the catch-all.

Use-case tests then cover three behaviors with a mocked repo: happy path (repo called
with the right filters, response truthy, `response.value` = domain objects), repo raising
(`repo.list.side_effect = Exception(...)` → `SYSTEM_ERROR` response, not a raise), and a
bad request (→ `PARAMETERS_ERROR` with the validation message).

### 2.5 Mocks hide integration drift — budget for it

Changing the use-case signature (`use_case(repo)` → `use_case(repo, request)`) keeps
**all unit tests green** because every collaborator is mocked, while the real Flask
server and CLI crash at runtime (`TypeError: missing positional argument`). This is
structural, not sloppiness: well-written unit tests isolate by design, so they *cannot*
detect that concrete adapters (endpoint code, repository implementations, CLI scripts)
are out of sync with a changed inner API.

Operational rule: **after any use-case API change, walk every adapter ring-by-ring** —
gateway/endpoint, then repository implementations, then CLI/entry scripts — and run at
least one end-to-end/integration check. Unit tests green ≠ system runs.

Also note the filter-placement decision: filtering *could* be use-case logic, but
delegating it to the repository (`repo.list(filters=...)`) exploits what databases are
good at. That makes filters part of the repository interface contract, which every
implementation must honor. The request-object filter grammar and the repository filter
grammar matching each other is a design choice, not a requirement.

---

## 3. Real database (Postgres): repository swap + integration testing

### 3.1 What makes the swap cheap

The use case depends only on the repository's **method API** (`list(filters=None)` here).
Two crucial reliefs:

- `__init__` is **not part of the contract.** The composition root (endpoint/CLI/main)
  constructs the repository, so each implementation can take whatever it needs:
  `MemRepo(seed_list)` vs `PostgresRepo(config_dict)`. Use cases never see construction.
- The repository **returns domain models**, converting from storage records internally.
  This is legitimate precisely because the repository lives in an outer layer and is
  allowed to know about the domain (inner layer); the domain never knows about it.

### 3.2 ORM classes ≠ domain models

Define a *separate* SQLAlchemy declarative class for the table, even when it looks nearly
identical to the domain entity:

```python
# myapp/repository/postgres_objects.py
from sqlalchemy import Column, Integer, String, Float
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class Room(Base):
    __tablename__ = "room"
    id = Column(Integer, primary_key=True)
    code = Column(String(36), nullable=False)
    size = Column(Integer)
    price = Column(Integer)
    longitude = Column(Float)
    latitude = Column(Float)
```

The table class is shaped by **storage needs** (surrogate PK, column types, maybe a JSON
column for coordinates), the entity by **business needs**. They start out overlapping and
diverge over time; keeping them separate means schema decisions never ripple into the
domain. Cost you accept: you keep the two in sync yourself and manage migrations
(Alembic) explicitly — migrations do not fall out of domain-model edits.

### 3.3 The Postgres repository

```python
# myapp/repository/postgresrepo.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from myapp.domain import room
from myapp.repository.postgres_objects import Base, Room

class PostgresRepo:
    def __init__(self, configuration):
        conn_str = (
            "postgresql+psycopg2://{}:{}@{}:{}/{}".format(
                configuration["POSTGRES_USER"],
                configuration["POSTGRES_PASSWORD"],
                configuration["POSTGRES_HOSTNAME"],
                configuration["POSTGRES_PORT"],
                configuration["APPLICATION_DB"],
            )
        )
        self.engine = create_engine(conn_str)
        Base.metadata.create_all(self.engine)

    def _to_domain(self, records):
        return [
            room.Room(
                code=r.code, size=r.size, price=r.price,
                latitude=r.latitude, longitude=r.longitude,
            )
            for r in records
        ]

    def list(self, filters=None):
        session = sessionmaker(bind=self.engine)()
        query = session.query(Room)
        if filters is None:
            return self._to_domain(query.all())
        if "code__eq" in filters:
            query = query.filter(Room.code == filters["code__eq"])
        if "price__eq" in filters:
            query = query.filter(Room.price == filters["price__eq"])
        if "price__lt" in filters:
            query = query.filter(Room.price < filters["price__lt"])
        if "price__gt" in filters:
            query = query.filter(Room.price > filters["price__gt"])
        return self._to_domain(query.all())
```

It mirrors `MemRepo` almost line-for-line at this complexity level; expect divergence as
use cases start leaning on engine-specific capabilities. The identical interface is the
point — the endpoint changes one constructor call and nothing else. Same recipe extends
to MongoDB or any other store: same method contract, different `__init__` and internals.

### 3.4 Never mock an ORM — integration-test it

Mocking SQLAlchemy query chains produces grotesque, unmaintainable mock setups (nested
`sessionmaker_mock()().query...` assertions) that break on every query refactor. The
rule: **mock the repository when testing use cases; integration-test the repository
itself against a real engine.** Mocks also cannot prove that two real systems speak the
same protocol — that is precisely the integration test's job.

### 3.5 Mark integration tests, skip them by default

Integration tests are slow (container startup) and need infrastructure, so they must be
opt-in:

```python
# tests/repository/postgres/test_postgresrepo.py
import pytest
pytestmark = pytest.mark.integration   # marks every test in the module
```

```ini
# pytest.ini
[pytest]
markers =
    integration: integration tests
```

```python
# tests/conftest.py — skip unless explicitly enabled
def pytest_addoption(parser):
    parser.addoption("--integration", action="store_true",
                     help="run integration tests")

def pytest_runtest_setup(item):
    if "integration" in item.keywords and not item.config.getvalue("integration"):
        pytest.skip("need --integration option to run")
```

Now `pytest` skips them, `pytest --integration` runs everything, and
`pytest -m integration` selects only them.

### 3.6 Orchestration: management script spins Postgres in Docker

Pattern: a `manage.py` (click-based) command wraps the whole integration run —
environment config → `docker-compose up -d` → wait for readiness → create test DB →
run pytest → `docker-compose down`. Environment-specific config lives in JSON files
(`config/testing.json`) plus per-environment compose files (`docker/testing.yml`).

Essential mechanics, condensed:

```python
# manage.py (skeleton)
import os, json, subprocess, time
import click, psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

def setenv(var, default):
    os.environ[var] = os.getenv(var, default)   # env wins over config file

def read_json_configuration(config):
    with open(f"config/{config}.json") as f:
        return {item["name"]: item["value"] for item in json.load(f)}

def configure_app(config):
    for key, value in read_json_configuration(config).items():
        setenv(key, value)

def compose_cmd(*extra):
    config = os.getenv("APPLICATION_CONFIG")
    return ["docker-compose", "-p", config, "-f", f"docker/{config}.yml", *extra]

def wait_for_logs(cmdline, message):
    while message not in subprocess.check_output(cmdline).decode("utf-8"):
        time.sleep(1)

def run_sql(statements):
    conn = psycopg2.connect(
        dbname=os.getenv("POSTGRES_DB"), user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
        host=os.getenv("POSTGRES_HOSTNAME"), port=os.getenv("POSTGRES_PORT"),
    )
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)  # CREATE DATABASE can't run in a tx
    cur = conn.cursor()
    for s in statements:
        cur.execute(s)
    cur.close(); conn.close()

@click.group()
def cli(): ...

@cli.command()
@click.argument("args", nargs=-1)
def test(args):
    os.environ["APPLICATION_CONFIG"] = "testing"
    configure_app("testing")
    subprocess.call(compose_cmd("up", "-d"))
    wait_for_logs(compose_cmd("logs", "postgres"), "ready to accept connections")
    run_sql([f"CREATE DATABASE {os.getenv('APPLICATION_DB')}"])
    subprocess.call(["pytest", "-svv", *args])
    subprocess.call(compose_cmd("down"))
```

```yaml
# docker/testing.yml
version: '3.8'
services:
  postgres:
    image: postgres
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    ports:
      - "${POSTGRES_PORT}:5432"
```

Gotchas baked into this setup:

- **Wait for readiness.** Containers have startup latency; poll the container logs for
  Postgres's "ready to accept connections" line before touching the DB. Connecting
  immediately after `up -d` fails intermittently.
- **Non-default host port** (e.g. 5433→5432) so the test container never collides with a
  natively running or otherwise-containerized Postgres. Only the host-side mapping
  changes; inside the container it is still 5432.
- **Dedicated application DB** (`APPLICATION_DB=test`) created via `run_sql`, separate
  from the default `postgres` DB the image auto-creates from `POSTGRES_DB`.
- `CREATE DATABASE` requires autocommit isolation in psycopg2.
- Click swallows unknown options: pass pytest flags after `--`, e.g.
  `./manage.py test -- --integration`.
- Container create/destroy is expensive → do it once around the whole suite (the
  management script), not per test.

### 3.7 Fixture stack for DB tests

Three layers, from broad to narrow:

```python
# tests/conftest.py
from manage import read_json_configuration

@pytest.fixture(scope="session")
def app_configuration():
    return read_json_configuration("testing")   # same config the script used
```

```python
# tests/repository/postgres/conftest.py
import sqlalchemy, pytest
from myapp.repository.postgres_objects import Base, Room

@pytest.fixture(scope="session")
def pg_session_empty(app_configuration):
    conn_str = "postgresql+psycopg2://{}:{}@{}:{}/{}".format(
        app_configuration["POSTGRES_USER"],
        app_configuration["POSTGRES_PASSWORD"],
        app_configuration["POSTGRES_HOSTNAME"],
        app_configuration["POSTGRES_PORT"],
        app_configuration["APPLICATION_DB"],
    )
    engine = sqlalchemy.create_engine(conn_str)
    connection = engine.connect()
    Base.metadata.create_all(engine)           # create schema once per session
    session = sqlalchemy.orm.sessionmaker(bind=engine)()
    yield session
    session.close()
    connection.close()

@pytest.fixture(scope="session")
def pg_test_data():
    return [ {...}, {...} ]                    # plain dicts of seed rows

@pytest.fixture(scope="function")
def pg_session(pg_session_empty, pg_test_data):
    for row in pg_test_data:
        pg_session_empty.add(Room(**row))      # ORM objects, NOT domain entities
    pg_session_empty.commit()
    yield pg_session_empty
    pg_session_empty.query(Room).delete()      # clean slate after every test
```

Scoping logic: engine/schema = `session` scope (expensive, do once); data seeding +
cleanup = `function` scope (every test starts from the same rows and leaves the DB as it
found it). Clean up even when current tests are read-only — the discipline pays off the
first time someone adds a write test.

The integration tests themselves then read exactly like the in-memory repository's unit
tests — construct `PostgresRepo(app_configuration)`, call `.list(filters=...)`, assert on
returned domain objects. Reusing the same test conditions across every repository
implementation is expected and good; the files may diverge later as implementation-
specific corner cases surface.

---

## 4. Actionable rules & anti-patterns

### Rules

1. **One use case, many faces.** CLI, HTTP endpoint, worker — all call the identical
   `use_case(repo, request)` line. Any interface-specific code stays in that interface's
   gateway.
2. **App factory + config classes** for any Flask-like framework; module-level app
   singletons kill testability.
3. **Endpoint = translation only**: parse transport input → build request object → wire
   repo → call use case → map `response.type` to a transport status via a static table.
4. **Validate at the request-builder boundary.** Use cases receive either a valid request
   or a falsy invalid one; they never re-validate parameters.
5. **Accumulate all validation errors** as `{parameter, message}` records; whitelist
   accepted keys/operators explicitly.
6. **Use cases return, never raise.** Wrap the body in `try/except Exception` →
   `SYSTEM_ERROR`; map anticipated conditions to `PARAMETERS_ERROR`/`RESOURCE_ERROR`.
7. **Three-type error taxonomy** (parameters / resource / system) as the baseline; keep
   the HTTP mapping in the gateway.
8. **Repository `__init__` is not part of the interface** — only the query/command
   methods are. Construction happens at the composition root.
9. **Repositories return domain models**, translating from storage records internally.
10. **Separate ORM table classes from domain entities**, even when nearly identical
    today; own your migrations explicitly.
11. **Mock repositories in use-case tests; never mock the ORM.** Test concrete
    repositories against a real engine.
12. **Mark integration tests** (`pytestmark = pytest.mark.integration`), register the
    marker, and gate them behind an explicit CLI flag so the default run stays fast.
13. **Orchestrate DB lifecycle around the suite**, not per test: compose up → wait for
    log-line readiness → create dedicated test DB → pytest → compose down.
14. **Fixture scoping:** engine/schema per session; seed + cleanup per function; share
    connection config between the orchestration script and fixtures from one source.
15. **After changing a use-case signature, sweep every adapter** (endpoints, repos, CLI)
    and run an end-to-end check — green unit tests prove nothing about wiring.

### Anti-patterns

- ❌ Letting the web framework's ORM/models double as domain entities — welds the domain
  to a delivery detail.
- ❌ Raising exceptions out of use cases and catching them in endpoints — failure shape
  becomes framework-specific and untypeable.
- ❌ Validation sprinkled inside use-case bodies instead of the request builder.
- ❌ Returning the first validation error only; callers then fix input one error per
  round trip.
- ❌ Mocking SQLAlchemy sessions/queries — write-only mock code that shatters on any
  query change.
- ❌ Trusting an all-mocked green suite as proof the system works after an inner-API
  change (the drift is invisible by construction).
- ❌ Integration tests that run on every `pytest` invocation — the suite slows, people
  stop running it.
- ❌ Spinning the DB container per test instead of per suite.
- ❌ Connecting to a just-started DB container without a readiness wait.
- ❌ Test DB on the default host port — collides with local Postgres instances.
- ❌ Tests that leave rows behind ("this test only reads anyway") — cleanup in the
  fixture teardown, always.
- ❌ Shadowing the framework's `request` name with your use-case request in views/tests.

# Clean Architecture in Python — Part 3: Backend Swapping & Production Deployment

Distilled operational knowledge from the final chunk of Giordani's *Clean Architectures in Python, 2nd ed.* (chapters on MongoDB integration and running a production-ready system). All prose and code here is original paraphrase/reimplementation — patterns only, no book text.

---

## 1. The backend-swap test: proof the architecture works

The single strongest validation of a clean architecture is adding a **second, radically different storage backend** (NoSQL Mongo next to relational Postgres) and observing how little changes.

### What changes when you add MongoDB

Only the outermost layer grows. You add exactly:

1. A new repository class (`MongoRepo`) in the repository/gateway package.
2. A new integration-test module + conftest fixtures for that backend.
3. One new service block in the *testing* docker-compose file.
4. A handful of new config entries (host/port/user/password for Mongo).
5. One line in the production requirements file (`pymongo`).

### What stays untouched — the whole point

- **Entities** (domain models) — zero changes.
- **Use cases** — zero changes. The same use case function consumes either repo.
- **Request/response objects, serializers** — zero changes.
- **HTTP layer** — zero changes (same endpoint drives either backend).
- **Unit tests for all of the above** — zero changes.

If adding a backend forces edits anywhere *inside* the boundary, that is a leak: the inner layers know about storage details and the architecture has failed its main promise.

### The repository contract is the pivot

Both repos expose the same duck-typed interface (`list(filters=None)` returning **domain entities**, never driver rows/documents). The keys of the `filters` dict use a backend-neutral convention (`"price__lt"`, `"code__eq"`); each repo translates that convention into its native query language:

- SQL repo → SQLAlchemy query/filter expressions.
- Mongo repo → a Mongo filter document (`{"price": {"$lt": 60}}`).

Minimal shape of the second backend (fresh illustrative code, not the book's):

```python
import pymongo
from myapp.domain.room import Room

class MongoRepo:
    def __init__(self, cfg):
        client = pymongo.MongoClient(
            host=cfg["MONGODB_HOSTNAME"],
            port=int(cfg["MONGODB_PORT"]),
            username=cfg["MONGODB_USER"],
            password=cfg["MONGODB_PASSWORD"],
            authSource="admin",
        )
        self.db = client[cfg["APPLICATION_DB"]]

    def _to_entities(self, docs):
        # ALWAYS re-hydrate into domain entities before crossing the boundary
        return [Room(code=d["code"], size=d["size"], price=d["price"],
                     latitude=d["latitude"], longitude=d["longitude"])
                for d in docs]

    def list(self, filters=None):
        coll = self.db.rooms
        if filters is None:
            return self._to_entities(coll.find())
        query = {}
        for compound_key, value in filters.items():
            field, op = compound_key.split("__")        # "price__lt" -> ("price", "lt")
            if field == "price":
                value = int(value)                       # normalize types at the boundary
            query.setdefault(field, {})[f"${op}"] = value
        return self._to_entities(coll.find(query))
```

Key implementation details worth copying:

- **Type coercion belongs in the repo.** Query-string values arrive as strings; Mongo will silently match nothing if you compare `"60"` against integer `60`. The repo converts (`int(value)`) so callers never care. Postgres/SQLAlchemy may coerce for you — Mongo won't. Backend-specific quirks are exactly what the repo layer exists to absorb.
- **Merge multiple operators on the same field.** `{"price__gt": 48, "price__lt": 66}` must fold into one document: `{"price": {"$gt": 48, "$lt": 66}}` — build the per-field dict incrementally, don't overwrite.
- **Return entities, not driver objects.** A `_to_entities`/`_create_*_objects` helper is the mandatory last step of every read path. (The book's own changelog records a real bug where a repo returned raw query results and no test caught it — see §3.)

### Test strategy for the second backend

Mirror the first backend's integration tests nearly verbatim: same fixture architecture, parallel names (`mg_database_empty` / `mg_database` / `mg_test_data` mirroring the `pg_*` ones), same assertions, same `pytest.mark.integration` marker. This duplication is *deliberate and fine* when both backends serve the same use case — you're verifying the same contract against two implementations. Fixture layering to reuse:

- **Session-scoped** fixture: create client + database once, drop database + close client on teardown.
- **Function-scoped** fixture: insert known test documents, `yield`, delete all documents — every test gets a pristine dataset.
- App-level configuration fixture is shared across backends (that's the payoff of building the test harness properly the first time).

Add a **defensive test per discovered quirk**: the author found via manual shell experimentation that string-typed price filters silently failed on Mongo, so he added a test pinning the coercion behavior. Rule: any surprising backend behavior found interactively becomes a regression test immediately.

---

## 2. Production stack: everything is an outer-layer detail

The production setup (WSGI server, reverse proxy, container orchestration, migrations) is explicitly **not part of the clean architecture** — it's plumbing around it. But the same decoupling makes the plumbing simple.

### Topology

```
client → Nginx (reverse proxy / would-be LB, :8080)
       → gunicorn (WSGI server, 4 workers, :8000)
       → Flask app (thin HTTP adapter)
       → use case → repository → Postgres (with named volume)
```

- **Never expose the framework dev server.** Production = real WSGI server (gunicorn) fronted by a real web server (Nginx).
- gunicorn loads the app from a tiny `wsgi.py` entry module: `gunicorn -w 4 -b 0.0.0.0 wsgi:app`.
- Nginx proxies to the upstream by compose service name (`server web:8000;`) and sets the standard forwarding headers (`Host`, `X-Real-IP`, `X-Forwarded-For`, `X-Forwarded-Host`).
- Use non-standard host ports (8080, not 80; 27018 for test Mongo, not 27017; 5433 for test Postgres, not 5432) so test/dev stacks coexist with anything else running on the machine. In richer setups, assign **random ports** and have the tooling read them back and inject into the app.

### Configuration management pattern

One machine-readable config file per environment (the book uses JSON lists of `{"name": ..., "value": ...}` pairs), e.g. `config/testing.json`, `config/production.json`. A single management script (`manage.py`, built on Click) is the only thing that reads these files; it exports the entries as **environment variables**, then execs the real tool (docker-compose, pytest, etc.). Consequences:

- Docker Compose, the test framework, and the app all consume the *same* variables from the *same* source — no drift between what tests use and what production uses.
- The application itself reads only `os.environ` — it never knows which environment it's in beyond the values it's given.
- Distinguish the two Flask-style knobs: the framework's own mode switch (`FLASK_ENV`, fixed vocabulary) vs. your own config selector (`FLASK_CONFIG`, an arbitrary name that picks a config object like `ProductionConfig`). Don't conflate them.
- Environment separation = a new JSON file + a compose file, nothing else. Testing vs production differ only in variable values (ports, database names) and which containers run.

Management-script skeleton (own code):

```python
import os, json, signal, subprocess
import click

def setenv(var, default):
    os.environ[var] = os.getenv(var, default)

setenv("APPLICATION_CONFIG", "production")   # explicit default

def configure_app(config_name):
    path = os.path.join("config", f"{config_name}.json")
    for item in json.load(open(path)):
        setenv(item["name"], item["value"])

@click.group()
def cli(): ...

@cli.command(context_settings={"ignore_unknown_options": True})
@click.argument("subcommand", nargs=-1, type=click.Path())
def compose(subcommand):
    """Pass-through wrapper: env from JSON config, then docker-compose."""
    configure_app(os.getenv("APPLICATION_CONFIG"))
    cmd = docker_compose_cmdline() + list(subcommand)
    try:
        p = subprocess.Popen(cmd)
        p.wait()
    except KeyboardInterrupt:
        p.send_signal(signal.SIGINT)   # forward Ctrl-C cleanly to compose
        p.wait()
```

Usage: `./manage.py compose build web`, `./manage.py compose up -d`, `./manage.py compose down`, `./manage.py compose exec db psql -U postgres`. One entry point wraps the whole ops surface; subcommands flow through untouched.

### Docker specifics that matter

- **Named volume for the database** (`pgdata:/var/lib/postgresql/data` + top-level `volumes:` declaration). Without it, all data dies with the container. Test DBs are deliberately ephemeral (no volume); the production DB is deliberately durable.
- Production web Dockerfile is minimal: official `python:3` base, `ENV PYTHONUNBUFFERED 1` (so logs stream instead of buffering), copy requirements, `pip install` the **production** requirements only.
- Split requirements files (`requirements/prod.txt` vs `dev.txt`, dev including prod). Server-only deps (gunicorn, alembic, DB drivers) live in prod; test tooling stays out of the image.
- The web container gets `POSTGRES_HOSTNAME: "db"` — the compose service name, not localhost. Inside the compose network, services address each other by name; only host-side tools use localhost + mapped ports.
- The DB container's auto-created database (from `POSTGRES_DB`) is *not* your application database (`APPLICATION_DB`). Create the app DB explicitly with an idempotent management command:

```python
@cli.command()
def init_postgres():
    configure_app(os.getenv("APPLICATION_CONFIG"))
    try:
        run_sql([f"CREATE DATABASE {os.getenv('APPLICATION_DB')}"])
    except psycopg2.errors.DuplicateDatabase:
        print("database already exists; skipping")   # safe to re-run
```

(Note: Click converts `init_postgres` → CLI command `init-postgres`.)

### Wiring the app to the real repository

Switching the HTTP endpoint from the in-memory repo to Postgres is a **two-line change**: instantiate `PostgresRepo(config_dict)` instead of `MemRepo(seed_data)`, where the config dict is assembled from `os.environ` at module level. The use case invocation, request building, serialization, and status-code mapping are untouched. Map response types to HTTP codes with a plain dict at the adapter layer:

```python
STATUS_CODES = {
    ResponseTypes.SUCCESS: 200,
    ResponseTypes.RESOURCE_ERROR: 404,
    ResponseTypes.PARAMETERS_ERROR: 400,
    ResponseTypes.SYSTEM_ERROR: 500,
}
```

This "swap one constructor call" moment is the production-side replay of the backend-swap test from §1 — the third repo (memory → Postgres → Mongo) plugged into an unchanged core.

### Migrations (Alembic) — schema lives outside the domain

Entities are storage-agnostic; **tables are not entities**. The ORM mapping classes live in the repository layer, and their DDL is managed by Alembic migrations — an external-system concern, never a domain one.

Setup recipe:

1. `alembic init migrations` in the project root (directory name arbitrary).
2. In `migrations/env.py`: inject DB credentials from environment variables into Alembic's INI section via `config.set_section_option(section, "POSTGRES_USER", os.environ.get(...))` etc., and point `target_metadata` at your ORM declarative `Base.metadata` (import from the repository package — enables autogenerate).
3. In `alembic.ini`: build the URL with ConfigParser interpolation so no secrets are hardcoded:
   `sqlalchemy.url = postgresql://%(POSTGRES_USER)s:%(POSTGRES_PASSWORD)s@%(POSTGRES_HOSTNAME)s/%(APPLICATION_DB)s`
4. Generate: `alembic revision --autogenerate -m "Initial"` (with env vars set — via the management script, or inline for a one-off).
5. Apply: `alembic upgrade head` (containers must be up; Alembic connects to the live DB).

Verification loop after migrating: exec `psql` inside the DB container, `\l` (databases), `\c appdb`, `\dt` (expect your tables **plus** `alembic_version`), `\d tablename` (columns), `SELECT * FROM alembic_version;` — the stored hash must match the newest migration filename. Insert a row manually, hit the HTTP endpoint, confirm the full path Nginx → gunicorn → Flask → use case → repo → DB returns it.

---

## 3. Testing & deployment guidance (residual)

- **Layered fixture reuse pays compound interest.** The "expensive" test harness (compose-managed containers, config-driven fixtures) built for backend #1 makes backend #2 almost free. Budget harness effort accordingly.
- **Integration tests are markered** (`pytestmark = pytest.mark.integration`) so the fast unit suite runs without any containers, and integration runs are an explicit opt-in.
- **Tests must assert on the *type* of returned objects,** not just field values. Documented real-world bug: a repo returned raw ORM rows instead of domain entities and the suite stayed green because assertions only compared attribute values. Assert `isinstance(result[0], Room)` or equivalent in at least one repo test per backend.
- **Duplicated test batteries across backends are legitimate** when the backends implement one shared contract; unify only if you serve genuinely different use cases per store.
- Manual DB inserts via `psql` are acceptable for smoke-testing a fresh stack; a real system adds a write endpoint.
- The demo stack knowingly omits HTTPS, tuned worker counts, real load balancing, secret management — the *shape* (proxy → WSGI → app → DB, config from env, migrations versioned) is what carries to real production; the numbers and hardening are load/business-dependent.

---

## 4. Actionable rules

1. **Prove the architecture by swapping storage.** If a second backend touches anything besides repository + its tests + config/compose entries, you have a boundary leak — fix the leak, not the backend.
2. **Repositories translate; cores stay dialect-free.** The neutral filter convention (`field__op`) is defined by the inner layers; each repo owns the translation to SQL/Mongo/whatever.
3. **Repos always return domain entities.** Never let ORM rows or BSON documents cross into use cases. Enforce with a type-asserting test.
4. **Normalize input types at the repo boundary** (string → int, etc.). Different drivers have different coercion behavior; callers must not need to know.
5. **One config source per environment, consumed as env vars, by everything.** App, tests, compose, migrations all read the same variables. New environment = new config file, zero code changes.
6. **Wrap ops in one management script.** A single Click CLI that loads config and delegates (compose passthrough, `init-postgres`, migrations) beats a README full of copy-paste commands; forward SIGINT properly.
7. **WSGI server + reverse proxy, never the dev server.** gunicorn behind Nginx; proxy by compose service name; set forwarding headers.
8. **Persistent named volume for production data; none for test DBs.** Ephemerality is a feature in tests and a catastrophe in prod.
9. **App database creation is an explicit, idempotent step** — distinct from the container's auto-created default DB. Safe to re-run.
10. **Schema changes only via versioned migrations** (Alembic), credentials injected from env, `target_metadata` wired for autogenerate; verify applied version against the migration filename.
11. **Every interactively-discovered backend quirk becomes a pinned test** the same day (the string-price-filter lesson).
12. **Keep prod requirements minimal and separate**; the production image installs only what serving needs.

## 5. Anti-patterns

- ❌ Use case or endpoint importing a DB driver / ORM session — storage detail above the boundary.
- ❌ Editing entities or use cases to "support" a new database — the definition of a failed architecture.
- ❌ Repo returning driver-native objects; tests that only check field values and would never catch it.
- ❌ Comparing unconverted query-string values against typed DB fields (silent empty results on Mongo).
- ❌ Overwriting the per-field filter dict when two operators target one field (`gt` + `lt` on price).
- ❌ Hardcoding credentials in `alembic.ini` / compose files instead of interpolating env vars.
- ❌ Production DB container without a named volume (data vanishes on `compose down`).
- ❌ Confusing the framework's fixed mode flag with your own free-form config selector.
- ❌ Serving traffic with the framework's built-in dev server, or exposing gunicorn directly without a proxy.
- ❌ `CREATE DATABASE` scripts that crash on re-run instead of catching duplicate-database errors.
- ❌ Standard host ports for test containers — collides with local services and parallel stacks.
- ❌ Treating docker/Nginx/gunicorn/migrations as "architecture": they're replaceable outer details; keeping them out of the core is precisely what makes them easy to change.

