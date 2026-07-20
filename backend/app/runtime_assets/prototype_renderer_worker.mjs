// scripts/prototype-renderer-worker.ts
import { createHash } from "node:crypto";

// src/features/prototype/runtime/canonical.ts
var textEncoder = new TextEncoder();
function compareUnicodeCodePoints(left, right) {
  const leftPoints = Array.from(left);
  const rightPoints = Array.from(right);
  const length2 = Math.min(leftPoints.length, rightPoints.length);
  for (let index = 0; index < length2; index += 1) {
    const leftPoint = leftPoints[index]?.codePointAt(0);
    const rightPoint = rightPoints[index]?.codePointAt(0);
    if (leftPoint === void 0 || rightPoint === void 0 || leftPoint === rightPoint) {
      continue;
    }
    return leftPoint < rightPoint ? -1 : 1;
  }
  if (leftPoints.length === rightPoints.length) return 0;
  return leftPoints.length < rightPoints.length ? -1 : 1;
}
function assertWellFormedString(value) {
  if (!value.isWellFormed()) {
    throw new TypeError("Canonical runtime strings must contain valid Unicode");
  }
}
function canonicalize(value) {
  if (value === null) {
    return "null";
  }
  if (typeof value === "string" || typeof value === "boolean") {
    if (typeof value === "string") assertWellFormedString(value);
    return JSON.stringify(value);
  }
  if (typeof value === "number") {
    if (!Number.isSafeInteger(value) || Object.is(value, -0)) {
      throw new TypeError("Canonical runtime numbers must be safe integers");
    }
    return String(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => canonicalize(item)).join(",")}]`;
  }
  if (typeof value === "object") {
    const entries = Object.entries(value).sort(
      ([left], [right]) => compareUnicodeCodePoints(left, right)
    );
    return `{${entries.map(([key, child]) => {
      assertWellFormedString(key);
      if (child === void 0) {
        throw new TypeError(`Canonical runtime object field ${key} is undefined`);
      }
      return `${JSON.stringify(key)}:${canonicalize(child)}`;
    }).join(",")}}`;
  }
  throw new TypeError(`Unsupported canonical runtime value type: ${typeof value}`);
}
function canonicalRuntimeJson(value) {
  return canonicalize(value);
}

// ../../../frontend/node_modules/xstate/dist/xstate-dev.esm.js
function getGlobal() {
  if (typeof globalThis !== "undefined") {
    return globalThis;
  }
  if (typeof self !== "undefined") {
    return self;
  }
  if (typeof window !== "undefined") {
    return window;
  }
  if (typeof global !== "undefined") {
    return global;
  }
}
function getDevTools() {
  const w = getGlobal();
  if (w.__xstate__) {
    return w.__xstate__;
  }
  return void 0;
}
var devToolsAdapter = (service) => {
  if (typeof window === "undefined") {
    return;
  }
  const devTools = getDevTools();
  if (devTools) {
    devTools.register(service);
  }
};

// ../../../frontend/node_modules/xstate/dist/raise-5fb0c8ca.esm.js
var Mailbox = class {
  constructor(_process) {
    this._process = _process;
    this._active = false;
    this._current = null;
    this._last = null;
  }
  start() {
    this._active = true;
    this.flush();
  }
  clear() {
    if (this._current) {
      this._current.next = null;
      this._last = this._current;
    }
  }
  enqueue(event) {
    const enqueued = {
      value: event,
      next: null
    };
    if (this._current) {
      this._last.next = enqueued;
      this._last = enqueued;
      return;
    }
    this._current = enqueued;
    this._last = enqueued;
    if (this._active) {
      this.flush();
    }
  }
  flush() {
    while (this._current) {
      const consumed = this._current;
      this._process(consumed.value);
      this._current = consumed.next;
    }
    this._last = null;
  }
};
var STATE_DELIMITER = ".";
var TARGETLESS_KEY = "";
var NULL_EVENT = "";
var STATE_IDENTIFIER = "#";
var WILDCARD = "*";
var XSTATE_INIT = "xstate.init";
var XSTATE_ERROR = "xstate.error";
var XSTATE_STOP = "xstate.stop";
function createAfterEvent(delayRef, id) {
  return {
    type: `xstate.after.${delayRef}.${id}`
  };
}
function createDoneStateEvent(id, output) {
  return {
    type: `xstate.done.state.${id}`,
    output
  };
}
function createDoneActorEvent(invokeId, output) {
  return {
    type: `xstate.done.actor.${invokeId}`,
    output,
    actorId: invokeId
  };
}
function createErrorActorEvent(id, error) {
  return {
    type: `xstate.error.actor.${id}`,
    error,
    actorId: id
  };
}
function createInitEvent(input) {
  return {
    type: XSTATE_INIT,
    input
  };
}
function reportUnhandledError(err) {
  setTimeout(() => {
    throw err;
  });
}
var symbolObservable = (() => typeof Symbol === "function" && Symbol.observable || "@@observable")();
function matchesState(parentStateId, childStateId) {
  const parentStateValue = toStateValue(parentStateId);
  const childStateValue = toStateValue(childStateId);
  if (typeof childStateValue === "string") {
    if (typeof parentStateValue === "string") {
      return childStateValue === parentStateValue;
    }
    return false;
  }
  if (typeof parentStateValue === "string") {
    return parentStateValue in childStateValue;
  }
  return Object.keys(parentStateValue).every((key) => {
    if (!(key in childStateValue)) {
      return false;
    }
    return matchesState(parentStateValue[key], childStateValue[key]);
  });
}
function toStatePath(stateId) {
  if (isArray(stateId)) {
    return stateId;
  }
  const result = [];
  let segment = "";
  for (let i = 0; i < stateId.length; i++) {
    const char = stateId.charCodeAt(i);
    switch (char) {
      // \
      case 92:
        segment += stateId[i + 1];
        i++;
        continue;
      // .
      case 46:
        result.push(segment);
        segment = "";
        continue;
    }
    segment += stateId[i];
  }
  result.push(segment);
  return result;
}
function toStateValue(stateValue) {
  if (isMachineSnapshot(stateValue)) {
    return stateValue.value;
  }
  if (typeof stateValue !== "string") {
    return stateValue;
  }
  const statePath = toStatePath(stateValue);
  return pathToStateValue(statePath);
}
function pathToStateValue(statePath) {
  if (statePath.length === 1) {
    return statePath[0];
  }
  const value = {};
  let marker = value;
  for (let i = 0; i < statePath.length - 1; i++) {
    if (i === statePath.length - 2) {
      marker[statePath[i]] = statePath[i + 1];
    } else {
      const previous = marker;
      marker = {};
      previous[statePath[i]] = marker;
    }
  }
  return value;
}
function mapValues(collection, iteratee) {
  const result = {};
  const collectionKeys = Object.keys(collection);
  for (let i = 0; i < collectionKeys.length; i++) {
    const key = collectionKeys[i];
    result[key] = iteratee(collection[key], key, collection, i);
  }
  return result;
}
function toArrayStrict(value) {
  if (isArray(value)) {
    return value;
  }
  return [value];
}
function toArray(value) {
  if (value === void 0) {
    return [];
  }
  return toArrayStrict(value);
}
function resolveOutput(mapper, context, event, self2) {
  if (typeof mapper === "function") {
    return mapper({
      context,
      event,
      self: self2
    });
  }
  return mapper;
}
function isArray(value) {
  return Array.isArray(value);
}
function isErrorActorEvent(event) {
  return event.type.startsWith("xstate.error.actor");
}
function toTransitionConfigArray(configLike) {
  return toArrayStrict(configLike).map((transitionLike) => {
    if (typeof transitionLike === "undefined" || typeof transitionLike === "string") {
      return {
        target: transitionLike
      };
    }
    return transitionLike;
  });
}
function normalizeTarget(target) {
  if (target === void 0 || target === TARGETLESS_KEY) {
    return void 0;
  }
  return toArray(target);
}
function toObserver(nextHandler, errorHandler, completionHandler) {
  const isObserver = typeof nextHandler === "object";
  const self2 = isObserver ? nextHandler : void 0;
  return {
    next: (isObserver ? nextHandler.next : nextHandler)?.bind(self2),
    error: (isObserver ? nextHandler.error : errorHandler)?.bind(self2),
    complete: (isObserver ? nextHandler.complete : completionHandler)?.bind(self2)
  };
}
function createInvokeId(stateNodeId, index) {
  return `${index}.${stateNodeId}`;
}
function resolveReferencedActor(machine, src) {
  const match = src.match(/^xstate\.invoke\.(\d+)\.(.*)/);
  if (!match) {
    return machine.implementations.actors[src];
  }
  const [, indexStr, nodeId] = match;
  const node = machine.getStateNodeById(nodeId);
  const invokeConfig = node.config.invoke;
  return (Array.isArray(invokeConfig) ? invokeConfig[indexStr] : invokeConfig).src;
}
function matchesEventDescriptor(eventType, descriptor) {
  if (descriptor === eventType) {
    return true;
  }
  if (descriptor === WILDCARD) {
    return true;
  }
  if (!descriptor.endsWith(".*")) {
    return false;
  }
  const partialEventTokens = descriptor.split(".");
  const eventTokens = eventType.split(".");
  for (let tokenIndex = 0; tokenIndex < partialEventTokens.length; tokenIndex++) {
    const partialEventToken = partialEventTokens[tokenIndex];
    const eventToken = eventTokens[tokenIndex];
    if (partialEventToken === "*") {
      const isLastToken = tokenIndex === partialEventTokens.length - 1;
      return isLastToken;
    }
    if (partialEventToken !== eventToken) {
      return false;
    }
  }
  return true;
}
function createScheduledEventId(actorRef, id) {
  return `${actorRef.sessionId}.${id}`;
}
var idCounter = 0;
function createSystem(rootActor, options) {
  const children = /* @__PURE__ */ new Map();
  const keyedActors = /* @__PURE__ */ new Map();
  const reverseKeyedActors = /* @__PURE__ */ new WeakMap();
  const inspectionObservers = /* @__PURE__ */ new Set();
  const timerMap = {};
  const {
    clock,
    logger
  } = options;
  const scheduler = {
    schedule: (source, target, event, delay, id = Math.random().toString(36).slice(2)) => {
      const scheduledEvent = {
        source,
        target,
        event,
        delay,
        id,
        startedAt: Date.now()
      };
      const scheduledEventId = createScheduledEventId(source, id);
      system._snapshot._scheduledEvents[scheduledEventId] = scheduledEvent;
      const timeout = clock.setTimeout(() => {
        delete timerMap[scheduledEventId];
        delete system._snapshot._scheduledEvents[scheduledEventId];
        system._relay(source, target, event);
      }, delay);
      timerMap[scheduledEventId] = timeout;
    },
    cancel: (source, id) => {
      const scheduledEventId = createScheduledEventId(source, id);
      const timeout = timerMap[scheduledEventId];
      delete timerMap[scheduledEventId];
      delete system._snapshot._scheduledEvents[scheduledEventId];
      if (timeout !== void 0) {
        clock.clearTimeout(timeout);
      }
    },
    cancelAll: (actorRef) => {
      for (const scheduledEventId in system._snapshot._scheduledEvents) {
        const scheduledEvent = system._snapshot._scheduledEvents[scheduledEventId];
        if (scheduledEvent.source === actorRef) {
          scheduler.cancel(actorRef, scheduledEvent.id);
        }
      }
    }
  };
  const sendInspectionEvent = (event) => {
    if (!inspectionObservers.size) {
      return;
    }
    const resolvedInspectionEvent = {
      ...event,
      rootId: rootActor.sessionId
    };
    inspectionObservers.forEach((observer) => observer.next?.(resolvedInspectionEvent));
  };
  const system = {
    _snapshot: {
      _scheduledEvents: (options?.snapshot && options.snapshot.scheduler) ?? {}
    },
    _bookId: () => `x:${idCounter++}`,
    _register: (sessionId, actorRef) => {
      children.set(sessionId, actorRef);
      return sessionId;
    },
    _unregister: (actorRef) => {
      children.delete(actorRef.sessionId);
      const systemId = reverseKeyedActors.get(actorRef);
      if (systemId !== void 0) {
        keyedActors.delete(systemId);
        reverseKeyedActors.delete(actorRef);
      }
    },
    get: (systemId) => {
      return keyedActors.get(systemId);
    },
    getAll: () => {
      return Object.fromEntries(keyedActors.entries());
    },
    _set: (systemId, actorRef) => {
      const existing = keyedActors.get(systemId);
      if (existing && existing !== actorRef) {
        throw new Error(`Actor with system ID '${systemId}' already exists.`);
      }
      keyedActors.set(systemId, actorRef);
      reverseKeyedActors.set(actorRef, systemId);
    },
    inspect: (observerOrFn) => {
      const observer = toObserver(observerOrFn);
      inspectionObservers.add(observer);
      return {
        unsubscribe() {
          inspectionObservers.delete(observer);
        }
      };
    },
    _sendInspectionEvent: sendInspectionEvent,
    _relay: (source, target, event) => {
      system._sendInspectionEvent({
        type: "@xstate.event",
        sourceRef: source,
        actorRef: target,
        event
      });
      target._send(event);
    },
    scheduler,
    getSnapshot: () => {
      return {
        _scheduledEvents: {
          ...system._snapshot._scheduledEvents
        }
      };
    },
    start: () => {
      const scheduledEvents = system._snapshot._scheduledEvents;
      system._snapshot._scheduledEvents = {};
      for (const scheduledId in scheduledEvents) {
        const {
          source,
          target,
          event,
          delay,
          id
        } = scheduledEvents[scheduledId];
        scheduler.schedule(source, target, event, delay, id);
      }
    },
    _clock: clock,
    _logger: logger
  };
  return system;
}
var executingCustomAction = false;
var $$ACTOR_TYPE = 1;
var ProcessingStatus = /* @__PURE__ */ (function(ProcessingStatus2) {
  ProcessingStatus2[ProcessingStatus2["NotStarted"] = 0] = "NotStarted";
  ProcessingStatus2[ProcessingStatus2["Running"] = 1] = "Running";
  ProcessingStatus2[ProcessingStatus2["Stopped"] = 2] = "Stopped";
  return ProcessingStatus2;
})({});
var defaultOptions = {
  clock: {
    setTimeout: (fn, ms) => {
      return setTimeout(fn, ms);
    },
    clearTimeout: (id) => {
      return clearTimeout(id);
    }
  },
  logger: console.log.bind(console),
  devTools: false
};
var Actor = class {
  /**
   * Creates a new actor instance for the given logic with the provided options,
   * if any.
   *
   * @param logic The logic to create an actor from
   * @param options Actor options
   */
  constructor(logic, options) {
    this.logic = logic;
    this._snapshot = void 0;
    this.clock = void 0;
    this.options = void 0;
    this.id = void 0;
    this.mailbox = new Mailbox(this._process.bind(this));
    this.observers = /* @__PURE__ */ new Set();
    this.eventListeners = /* @__PURE__ */ new Map();
    this.logger = void 0;
    this._processingStatus = ProcessingStatus.NotStarted;
    this._parent = void 0;
    this._syncSnapshot = void 0;
    this.ref = void 0;
    this._actorScope = void 0;
    this.systemId = void 0;
    this.sessionId = void 0;
    this.system = void 0;
    this._doneEvent = void 0;
    this.src = void 0;
    this._deferred = [];
    const resolvedOptions = {
      ...defaultOptions,
      ...options
    };
    const {
      clock,
      logger,
      parent,
      syncSnapshot,
      id,
      systemId,
      inspect
    } = resolvedOptions;
    this.system = parent ? parent.system : createSystem(this, {
      clock,
      logger
    });
    if (inspect && !parent) {
      this.system.inspect(toObserver(inspect));
    }
    this.sessionId = this.system._bookId();
    this.id = id ?? this.sessionId;
    this.logger = options?.logger ?? this.system._logger;
    this.clock = options?.clock ?? this.system._clock;
    this._parent = parent;
    this._syncSnapshot = syncSnapshot;
    this.options = resolvedOptions;
    this.src = resolvedOptions.src ?? logic;
    this.ref = this;
    this._actorScope = {
      self: this,
      id: this.id,
      sessionId: this.sessionId,
      logger: this.logger,
      defer: (fn) => {
        this._deferred.push(fn);
      },
      system: this.system,
      stopChild: (child) => {
        if (child._parent !== this) {
          throw new Error(`Cannot stop child actor ${child.id} of ${this.id} because it is not a child`);
        }
        child._stop();
      },
      emit: (emittedEvent) => {
        const listeners = this.eventListeners.get(emittedEvent.type);
        const wildcardListener = this.eventListeners.get("*");
        if (!listeners && !wildcardListener) {
          return;
        }
        const allListeners = [...listeners ? listeners.values() : [], ...wildcardListener ? wildcardListener.values() : []];
        for (const handler of allListeners) {
          try {
            handler(emittedEvent);
          } catch (err) {
            reportUnhandledError(err);
          }
        }
      },
      actionExecutor: (action) => {
        const exec = () => {
          this._actorScope.system._sendInspectionEvent({
            type: "@xstate.action",
            actorRef: this,
            action: {
              type: action.type,
              params: action.params
            }
          });
          if (!action.exec) {
            return;
          }
          const saveExecutingCustomAction = executingCustomAction;
          try {
            executingCustomAction = true;
            action.exec(action.info, action.params);
          } finally {
            executingCustomAction = saveExecutingCustomAction;
          }
        };
        if (this._processingStatus === ProcessingStatus.Running) {
          exec();
        } else {
          this._deferred.push(exec);
        }
      }
    };
    this.send = this.send.bind(this);
    this.system._sendInspectionEvent({
      type: "@xstate.actor",
      actorRef: this
    });
    if (systemId) {
      this.systemId = systemId;
      this.system._set(systemId, this);
    }
    this._initState(options?.snapshot ?? options?.state);
    if (systemId && this._snapshot.status !== "active") {
      this.system._unregister(this);
    }
  }
  _initState(persistedState) {
    try {
      this._snapshot = persistedState ? this.logic.restoreSnapshot ? this.logic.restoreSnapshot(persistedState, this._actorScope) : persistedState : this.logic.getInitialSnapshot(this._actorScope, this.options?.input);
    } catch (err) {
      this._snapshot = {
        status: "error",
        output: void 0,
        error: err
      };
    }
  }
  update(snapshot, event) {
    this._snapshot = snapshot;
    let deferredFn;
    while (deferredFn = this._deferred.shift()) {
      try {
        deferredFn();
      } catch (err) {
        this._deferred.length = 0;
        this._snapshot = {
          ...snapshot,
          status: "error",
          error: err
        };
      }
    }
    switch (this._snapshot.status) {
      case "active":
        for (const observer of this.observers) {
          try {
            observer.next?.(snapshot);
          } catch (err) {
            reportUnhandledError(err);
          }
        }
        break;
      case "done":
        for (const observer of this.observers) {
          try {
            observer.next?.(snapshot);
          } catch (err) {
            reportUnhandledError(err);
          }
        }
        this._stopProcedure();
        this._complete();
        this._doneEvent = createDoneActorEvent(this.id, this._snapshot.output);
        if (this._parent) {
          this.system._relay(this, this._parent, this._doneEvent);
        }
        break;
      case "error":
        this._error(this._snapshot.error);
        break;
    }
    this.system._sendInspectionEvent({
      type: "@xstate.snapshot",
      actorRef: this,
      event,
      snapshot
    });
  }
  /**
   * Subscribe an observer to an actor’s snapshot values.
   *
   * @remarks
   * The observer will receive the actor’s snapshot value when it is emitted.
   * The observer can be:
   *
   * - A plain function that receives the latest snapshot, or
   * - An observer object whose `.next(snapshot)` method receives the latest
   *   snapshot
   *
   * @example
   *
   * ```ts
   * // Observer as a plain function
   * const subscription = actor.subscribe((snapshot) => {
   *   console.log(snapshot);
   * });
   * ```
   *
   * @example
   *
   * ```ts
   * // Observer as an object
   * const subscription = actor.subscribe({
   *   next(snapshot) {
   *     console.log(snapshot);
   *   },
   *   error(err) {
   *     // ...
   *   },
   *   complete() {
   *     // ...
   *   }
   * });
   * ```
   *
   * The return value of `actor.subscribe(observer)` is a subscription object
   * that has an `.unsubscribe()` method. You can call
   * `subscription.unsubscribe()` to unsubscribe the observer:
   *
   * @example
   *
   * ```ts
   * const subscription = actor.subscribe((snapshot) => {
   *   // ...
   * });
   *
   * // Unsubscribe the observer
   * subscription.unsubscribe();
   * ```
   *
   * When the actor is stopped, all of its observers will automatically be
   * unsubscribed.
   *
   * @param observer - Either a plain function that receives the latest
   *   snapshot, or an observer object whose `.next(snapshot)` method receives
   *   the latest snapshot
   */
  subscribe(nextListenerOrObserver, errorListener, completeListener) {
    const observer = toObserver(nextListenerOrObserver, errorListener, completeListener);
    if (this._processingStatus !== ProcessingStatus.Stopped) {
      this.observers.add(observer);
    } else {
      switch (this._snapshot.status) {
        case "done":
          try {
            observer.complete?.();
          } catch (err) {
            reportUnhandledError(err);
          }
          break;
        case "error": {
          const err = this._snapshot.error;
          if (!observer.error) {
            reportUnhandledError(err);
          } else {
            try {
              observer.error(err);
            } catch (err2) {
              reportUnhandledError(err2);
            }
          }
          break;
        }
      }
    }
    return {
      unsubscribe: () => {
        this.observers.delete(observer);
      }
    };
  }
  on(type, handler) {
    let listeners = this.eventListeners.get(type);
    if (!listeners) {
      listeners = /* @__PURE__ */ new Set();
      this.eventListeners.set(type, listeners);
    }
    const wrappedHandler = handler.bind(void 0);
    listeners.add(wrappedHandler);
    return {
      unsubscribe: () => {
        listeners.delete(wrappedHandler);
      }
    };
  }
  select(selector, equalityFn = Object.is) {
    return {
      subscribe: (observerOrFn) => {
        const observer = toObserver(observerOrFn);
        const snapshot = this.getSnapshot();
        let previousSelected = selector(snapshot);
        return this.subscribe((snapshot2) => {
          const nextSelected = selector(snapshot2);
          if (!equalityFn(previousSelected, nextSelected)) {
            previousSelected = nextSelected;
            observer.next?.(nextSelected);
          }
        });
      },
      get: () => selector(this.getSnapshot())
    };
  }
  /** Starts the Actor from the initial state */
  start() {
    if (this._processingStatus === ProcessingStatus.Running) {
      return this;
    }
    if (this._syncSnapshot) {
      this.subscribe({
        next: (snapshot) => {
          if (snapshot.status === "active") {
            this.system._relay(this, this._parent, {
              type: `xstate.snapshot.${this.id}`,
              snapshot
            });
          }
        },
        error: () => {
        }
      });
    }
    this.system._register(this.sessionId, this);
    if (this.systemId) {
      this.system._set(this.systemId, this);
    }
    this._processingStatus = ProcessingStatus.Running;
    const initEvent = createInitEvent(this.options.input);
    this.system._sendInspectionEvent({
      type: "@xstate.event",
      sourceRef: this._parent,
      actorRef: this,
      event: initEvent
    });
    const status = this._snapshot.status;
    switch (status) {
      case "done":
        this.update(this._snapshot, initEvent);
        return this;
      case "error":
        this._error(this._snapshot.error);
        return this;
    }
    if (!this._parent) {
      this.system.start();
    }
    if (this.logic.start) {
      try {
        this.logic.start(this._snapshot, this._actorScope);
      } catch (err) {
        this._snapshot = {
          ...this._snapshot,
          status: "error",
          error: err
        };
        this._error(err);
        return this;
      }
    }
    this.update(this._snapshot, initEvent);
    if (this.options.devTools) {
      this.attachDevTools();
    }
    this.mailbox.start();
    return this;
  }
  _process(event) {
    let nextState;
    let caughtError;
    try {
      nextState = this.logic.transition(this._snapshot, event, this._actorScope);
    } catch (err) {
      caughtError = {
        err
      };
    }
    if (caughtError) {
      const {
        err
      } = caughtError;
      this._snapshot = {
        ...this._snapshot,
        status: "error",
        error: err
      };
      this._error(err);
      return;
    }
    this.update(nextState, event);
    if (event.type === XSTATE_STOP) {
      this._stopProcedure();
      this._complete();
    }
  }
  _stop() {
    if (this._processingStatus === ProcessingStatus.Stopped) {
      return this;
    }
    this.mailbox.clear();
    if (this._processingStatus === ProcessingStatus.NotStarted) {
      this._processingStatus = ProcessingStatus.Stopped;
      return this;
    }
    this.mailbox.enqueue({
      type: XSTATE_STOP
    });
    return this;
  }
  /** Stops the Actor and unsubscribe all listeners. */
  stop() {
    if (this._parent) {
      throw new Error("A non-root actor cannot be stopped directly.");
    }
    return this._stop();
  }
  _complete() {
    for (const observer of this.observers) {
      try {
        observer.complete?.();
      } catch (err) {
        reportUnhandledError(err);
      }
    }
    this.observers.clear();
    this.eventListeners.clear();
  }
  _reportError(err) {
    if (!this.observers.size) {
      if (!this._parent) {
        reportUnhandledError(err);
      }
      this.eventListeners.clear();
      return;
    }
    let reportError = false;
    for (const observer of this.observers) {
      const errorListener = observer.error;
      reportError ||= !errorListener;
      try {
        errorListener?.(err);
      } catch (err2) {
        reportUnhandledError(err2);
      }
    }
    this.observers.clear();
    this.eventListeners.clear();
    if (reportError) {
      reportUnhandledError(err);
    }
  }
  _error(err) {
    this._stopProcedure();
    this._reportError(err);
    if (this._parent) {
      this.system._relay(this, this._parent, createErrorActorEvent(this.id, err));
    }
  }
  // TODO: atm children don't belong entirely to the actor so
  // in a way - it's not even super aware of them
  // so we can't stop them from here but we really should!
  // right now, they are being stopped within the machine's transition
  // but that could throw and leave us with "orphaned" active actors
  _stopProcedure() {
    if (this._processingStatus !== ProcessingStatus.Running) {
      return this;
    }
    this.system.scheduler.cancelAll(this);
    this.mailbox.clear();
    this.mailbox = new Mailbox(this._process.bind(this));
    this._processingStatus = ProcessingStatus.Stopped;
    this.system._unregister(this);
    return this;
  }
  /** @internal */
  _send(event) {
    if (this._processingStatus === ProcessingStatus.Stopped) {
      return;
    }
    this.mailbox.enqueue(event);
  }
  /**
   * Sends an event to the running Actor to trigger a transition.
   *
   * @param event The event to send
   */
  send(event) {
    this.system._relay(void 0, this, event);
  }
  attachDevTools() {
    const {
      devTools
    } = this.options;
    if (devTools) {
      const resolvedDevToolsAdapter = typeof devTools === "function" ? devTools : devToolsAdapter;
      resolvedDevToolsAdapter(this);
    }
  }
  toJSON() {
    return {
      xstate$$type: $$ACTOR_TYPE,
      id: this.id
    };
  }
  /**
   * Obtain the internal state of the actor, which can be persisted.
   *
   * @remarks
   * The internal state can be persisted from any actor, not only machines.
   *
   * Note that the persisted state is not the same as the snapshot from
   * {@link Actor.getSnapshot}. Persisted state represents the internal state of
   * the actor, while snapshots represent the actor's last emitted value.
   *
   * Can be restored with {@link ActorOptions.state}
   * @see https://stately.ai/docs/persistence
   */
  getPersistedSnapshot(options) {
    return this.logic.getPersistedSnapshot(this._snapshot, options);
  }
  [symbolObservable]() {
    return this;
  }
  /**
   * Read an actor’s snapshot synchronously.
   *
   * @remarks
   * The snapshot represent an actor's last emitted value.
   *
   * When an actor receives an event, its internal state may change. An actor
   * may emit a snapshot when a state transition occurs.
   *
   * Note that some actors, such as callback actors generated with
   * `fromCallback`, will not emit snapshots.
   * @see {@link Actor.subscribe} to subscribe to an actor’s snapshot values.
   * @see {@link Actor.getPersistedSnapshot} to persist the internal state of an actor (which is more than just a snapshot).
   */
  getSnapshot() {
    return this._snapshot;
  }
};
function createActor(logic, ...[options]) {
  return new Actor(logic, options);
}
function resolveCancel(_, snapshot, actionArgs, actionParams, {
  sendId
}) {
  const resolvedSendId = typeof sendId === "function" ? sendId(actionArgs, actionParams) : sendId;
  return [snapshot, {
    sendId: resolvedSendId
  }, void 0];
}
function executeCancel(actorScope, params) {
  actorScope.defer(() => {
    actorScope.system.scheduler.cancel(actorScope.self, params.sendId);
  });
}
function cancel(sendId) {
  function cancel2(_args, _params) {
  }
  cancel2.type = "xstate.cancel";
  cancel2.sendId = sendId;
  cancel2.resolve = resolveCancel;
  cancel2.execute = executeCancel;
  return cancel2;
}
function resolveSpawn(actorScope, snapshot, actionArgs, _actionParams, {
  id,
  systemId,
  src,
  input,
  syncSnapshot
}) {
  const logic = typeof src === "string" ? resolveReferencedActor(snapshot.machine, src) : src;
  const resolvedId = typeof id === "function" ? id(actionArgs) : id;
  let actorRef;
  let resolvedInput = void 0;
  if (logic) {
    resolvedInput = typeof input === "function" ? input({
      context: snapshot.context,
      event: actionArgs.event,
      self: actorScope.self
    }) : input;
    actorRef = createActor(logic, {
      id: resolvedId,
      src,
      parent: actorScope.self,
      syncSnapshot,
      systemId,
      input: resolvedInput
    });
  }
  return [cloneMachineSnapshot(snapshot, {
    children: {
      ...snapshot.children,
      [resolvedId]: actorRef
    }
  }), {
    id,
    systemId,
    actorRef,
    src,
    input: resolvedInput
  }, void 0];
}
function executeSpawn(actorScope, {
  actorRef
}) {
  if (!actorRef) {
    return;
  }
  actorScope.defer(() => {
    if (actorRef._processingStatus === ProcessingStatus.Stopped) {
      return;
    }
    actorRef.start();
  });
}
function spawnChild(...[src, {
  id,
  systemId,
  input,
  syncSnapshot = false
} = {}]) {
  function spawnChild2(_args, _params) {
  }
  spawnChild2.type = "xstate.spawnChild";
  spawnChild2.id = id;
  spawnChild2.systemId = systemId;
  spawnChild2.src = src;
  spawnChild2.input = input;
  spawnChild2.syncSnapshot = syncSnapshot;
  spawnChild2.resolve = resolveSpawn;
  spawnChild2.execute = executeSpawn;
  return spawnChild2;
}
function resolveStop(_, snapshot, args, actionParams, {
  actorRef
}) {
  const actorRefOrString = typeof actorRef === "function" ? actorRef(args, actionParams) : actorRef;
  const resolvedActorRef = typeof actorRefOrString === "string" ? snapshot.children[actorRefOrString] : actorRefOrString;
  let children = snapshot.children;
  if (resolvedActorRef) {
    children = {
      ...children
    };
    delete children[resolvedActorRef.id];
  }
  return [cloneMachineSnapshot(snapshot, {
    children
  }), resolvedActorRef, void 0];
}
function unregisterRecursively(actorScope, actorRef) {
  const snapshot = actorRef.getSnapshot();
  if (snapshot && "children" in snapshot) {
    for (const child of Object.values(snapshot.children)) {
      unregisterRecursively(actorScope, child);
    }
  }
  actorScope.system._unregister(actorRef);
}
function executeStop(actorScope, actorRef) {
  if (!actorRef) {
    return;
  }
  unregisterRecursively(actorScope, actorRef);
  if (actorRef._processingStatus !== ProcessingStatus.Running) {
    actorScope.stopChild(actorRef);
    return;
  }
  actorScope.defer(() => {
    actorScope.stopChild(actorRef);
  });
}
function stopChild(actorRef) {
  function stop(_args, _params) {
  }
  stop.type = "xstate.stopChild";
  stop.actorRef = actorRef;
  stop.resolve = resolveStop;
  stop.execute = executeStop;
  return stop;
}
function checkAnd(snapshot, {
  context,
  event
}, {
  guards
}) {
  return guards.every((guard) => evaluateGuard(guard, context, event, snapshot));
}
function and(guards) {
  function and2(_args, _params) {
    return false;
  }
  and2.check = checkAnd;
  and2.guards = guards;
  return and2;
}
function evaluateGuard(guard, context, event, snapshot) {
  const {
    machine
  } = snapshot;
  const isInline = typeof guard === "function";
  const resolved = isInline ? guard : machine.implementations.guards[typeof guard === "string" ? guard : guard.type];
  if (!isInline && !resolved) {
    throw new Error(`Guard '${typeof guard === "string" ? guard : guard.type}' is not implemented.'.`);
  }
  if (typeof resolved !== "function") {
    return evaluateGuard(resolved, context, event, snapshot);
  }
  const guardArgs = {
    context,
    event
  };
  const guardParams = isInline || typeof guard === "string" ? void 0 : "params" in guard ? typeof guard.params === "function" ? guard.params({
    context,
    event
  }) : guard.params : void 0;
  if (!("check" in resolved)) {
    return resolved(guardArgs, guardParams);
  }
  const builtinGuard = resolved;
  return builtinGuard.check(
    snapshot,
    guardArgs,
    resolved
    // this holds all params
  );
}
function isAtomicStateNode(stateNode) {
  return stateNode.type === "atomic" || stateNode.type === "final";
}
function getChildren(stateNode) {
  return Object.values(stateNode.states).filter((sn) => sn.type !== "history");
}
function getProperAncestors(stateNode, toStateNode) {
  const ancestors = [];
  if (toStateNode === stateNode) {
    return ancestors;
  }
  let m = stateNode.parent;
  while (m && m !== toStateNode) {
    ancestors.push(m);
    m = m.parent;
  }
  return ancestors;
}
function getAllStateNodes(stateNodes) {
  const nodeSet = new Set(stateNodes);
  const adjList = getAdjList(nodeSet);
  for (const s of nodeSet) {
    if (s.type === "compound" && (!adjList.get(s) || !adjList.get(s).length)) {
      getInitialStateNodesWithTheirAncestors(s).forEach((sn) => nodeSet.add(sn));
    } else {
      if (s.type === "parallel") {
        for (const child of getChildren(s)) {
          if (child.type === "history") {
            continue;
          }
          if (!nodeSet.has(child)) {
            const initialStates = getInitialStateNodesWithTheirAncestors(child);
            for (const initialStateNode of initialStates) {
              nodeSet.add(initialStateNode);
            }
          }
        }
      }
    }
  }
  for (const s of nodeSet) {
    let m = s.parent;
    while (m) {
      nodeSet.add(m);
      m = m.parent;
    }
  }
  return nodeSet;
}
function getValueFromAdj(baseNode, adjList) {
  const childStateNodes = adjList.get(baseNode);
  if (!childStateNodes) {
    return {};
  }
  if (baseNode.type === "compound") {
    const childStateNode = childStateNodes[0];
    if (childStateNode) {
      if (isAtomicStateNode(childStateNode)) {
        return childStateNode.key;
      }
    } else {
      return {};
    }
  }
  const stateValue = {};
  for (const childStateNode of childStateNodes) {
    stateValue[childStateNode.key] = getValueFromAdj(childStateNode, adjList);
  }
  return stateValue;
}
function getAdjList(stateNodes) {
  const adjList = /* @__PURE__ */ new Map();
  for (const s of stateNodes) {
    if (!adjList.has(s)) {
      adjList.set(s, []);
    }
    if (s.parent) {
      if (!adjList.has(s.parent)) {
        adjList.set(s.parent, []);
      }
      adjList.get(s.parent).push(s);
    }
  }
  return adjList;
}
function getStateValue(rootNode, stateNodes) {
  const config = getAllStateNodes(stateNodes);
  return getValueFromAdj(rootNode, getAdjList(config));
}
function isInFinalState(stateNodeSet, stateNode) {
  if (stateNode.type === "compound") {
    return getChildren(stateNode).some((s) => s.type === "final" && stateNodeSet.has(s));
  }
  if (stateNode.type === "parallel") {
    return getChildren(stateNode).every((sn) => isInFinalState(stateNodeSet, sn));
  }
  return stateNode.type === "final";
}
var isStateId = (str) => str[0] === STATE_IDENTIFIER;
function getCandidates(stateNode, receivedEventType) {
  const exactMatch = stateNode.transitions.get(receivedEventType);
  const wildcardCandidates = [...stateNode.transitions.keys()].filter((eventDescriptor) => eventDescriptor !== receivedEventType && matchesEventDescriptor(receivedEventType, eventDescriptor)).sort((a, b) => b.length - a.length).flatMap((key) => stateNode.transitions.get(key));
  return exactMatch ? [...exactMatch, ...wildcardCandidates] : wildcardCandidates;
}
function getDelayedTransitions(stateNode) {
  const afterConfig = stateNode.config.after;
  if (!afterConfig) {
    return [];
  }
  const mutateEntryExit = (delay) => {
    const afterEvent = createAfterEvent(delay, stateNode.id);
    const eventType = afterEvent.type;
    stateNode.entry.push(raise(afterEvent, {
      id: eventType,
      delay
    }));
    stateNode.exit.push(cancel(eventType));
    return eventType;
  };
  const delayedTransitions = Object.keys(afterConfig).flatMap((delay) => {
    const configTransition = afterConfig[delay];
    const resolvedTransition = typeof configTransition === "string" ? {
      target: configTransition
    } : configTransition;
    const resolvedDelay = Number.isNaN(+delay) ? delay : +delay;
    const eventType = mutateEntryExit(resolvedDelay);
    return toArray(resolvedTransition).map((transition) => ({
      ...transition,
      event: eventType,
      delay: resolvedDelay
    }));
  });
  return delayedTransitions.map((delayedTransition) => {
    const {
      delay
    } = delayedTransition;
    return {
      ...formatTransition(stateNode, delayedTransition.event, delayedTransition),
      delay
    };
  });
}
function formatTransition(stateNode, descriptor, transitionConfig) {
  const normalizedTarget = normalizeTarget(transitionConfig.target);
  const reenter = transitionConfig.reenter ?? false;
  const target = resolveTarget(stateNode, normalizedTarget);
  const transition = {
    ...transitionConfig,
    actions: toArray(transitionConfig.actions),
    guard: transitionConfig.guard,
    target,
    source: stateNode,
    reenter,
    eventType: descriptor,
    toJSON: () => ({
      ...transition,
      source: `#${stateNode.id}`,
      target: target ? target.map((t) => `#${t.id}`) : void 0
    })
  };
  return transition;
}
function formatTransitions(stateNode) {
  const transitions = /* @__PURE__ */ new Map();
  if (stateNode.config.on) {
    for (const descriptor of Object.keys(stateNode.config.on)) {
      if (descriptor === NULL_EVENT) {
        throw new Error('Null events ("") cannot be specified as a transition key. Use `always: { ... }` instead.');
      }
      const transitionsConfig = stateNode.config.on[descriptor];
      transitions.set(descriptor, toTransitionConfigArray(transitionsConfig).map((t) => formatTransition(stateNode, descriptor, t)));
    }
  }
  if (stateNode.config.onDone) {
    const descriptor = `xstate.done.state.${stateNode.id}`;
    transitions.set(descriptor, toTransitionConfigArray(stateNode.config.onDone).map((t) => formatTransition(stateNode, descriptor, t)));
  }
  for (const invokeDef of stateNode.invoke) {
    if (invokeDef.onDone) {
      const descriptor = `xstate.done.actor.${invokeDef.id}`;
      transitions.set(descriptor, toTransitionConfigArray(invokeDef.onDone).map((t) => formatTransition(stateNode, descriptor, t)));
    }
    if (invokeDef.onError) {
      const descriptor = `xstate.error.actor.${invokeDef.id}`;
      transitions.set(descriptor, toTransitionConfigArray(invokeDef.onError).map((t) => formatTransition(stateNode, descriptor, t)));
    }
    if (invokeDef.onSnapshot) {
      const descriptor = `xstate.snapshot.${invokeDef.id}`;
      transitions.set(descriptor, toTransitionConfigArray(invokeDef.onSnapshot).map((t) => formatTransition(stateNode, descriptor, t)));
    }
  }
  for (const delayedTransition of stateNode.after) {
    let existing = transitions.get(delayedTransition.eventType);
    if (!existing) {
      existing = [];
      transitions.set(delayedTransition.eventType, existing);
    }
    existing.push(delayedTransition);
  }
  return transitions;
}
function formatRouteTransitions(rootStateNode) {
  const routeTransitions = [];
  const collectRoutes = (states) => {
    Object.values(states).forEach((sn) => {
      if (sn.config.route && sn.config.id) {
        const routeId = sn.config.id;
        const userGuard = sn.config.route.guard;
        const routeMatches = ({
          event
        }) => event.to === `#${routeId}`;
        const transition = {
          ...sn.config.route,
          guard: userGuard ? and([routeMatches, userGuard]) : routeMatches,
          target: `#${routeId}`
        };
        routeTransitions.push(formatTransition(rootStateNode, "xstate.route", transition));
      }
      if (sn.states) {
        collectRoutes(sn.states);
      }
    });
  };
  collectRoutes(rootStateNode.states);
  if (routeTransitions.length > 0) {
    rootStateNode.transitions.set("xstate.route", routeTransitions);
  }
}
function formatInitialTransition(stateNode, _target) {
  const resolvedTarget = typeof _target === "string" ? stateNode.states[_target] : _target ? stateNode.states[_target.target] : void 0;
  if (!resolvedTarget && _target) {
    throw new Error(
      // eslint-disable-next-line @typescript-eslint/restrict-template-expressions, @typescript-eslint/no-base-to-string
      `Initial state node "${_target}" not found on parent state node #${stateNode.id}`
    );
  }
  const transition = {
    source: stateNode,
    actions: !_target || typeof _target === "string" ? [] : toArray(_target.actions),
    eventType: null,
    reenter: false,
    target: resolvedTarget ? [resolvedTarget] : [],
    toJSON: () => ({
      ...transition,
      source: `#${stateNode.id}`,
      target: resolvedTarget ? [`#${resolvedTarget.id}`] : []
    })
  };
  return transition;
}
function resolveTarget(stateNode, targets) {
  if (targets === void 0) {
    return void 0;
  }
  return targets.map((target) => {
    if (typeof target !== "string") {
      return target;
    }
    if (isStateId(target)) {
      return stateNode.machine.getStateNodeById(target);
    }
    const isInternalTarget = target[0] === STATE_DELIMITER;
    if (isInternalTarget && !stateNode.parent) {
      return getStateNodeByPath(stateNode, target.slice(1));
    }
    const resolvedTarget = isInternalTarget ? stateNode.key + target : target;
    if (stateNode.parent) {
      try {
        const targetStateNode = getStateNodeByPath(stateNode.parent, resolvedTarget);
        return targetStateNode;
      } catch (err) {
        throw new Error(`Invalid transition definition for state node '${stateNode.id}':
${err.message}`);
      }
    } else {
      throw new Error(`Invalid target: "${target}" is not a valid target from the root node. Did you mean ".${target}"?`);
    }
  });
}
function resolveHistoryDefaultTransition(stateNode) {
  const normalizedTarget = normalizeTarget(stateNode.config.target);
  if (!normalizedTarget) {
    if (stateNode.parent.type === "parallel") {
      return {
        target: [stateNode.parent]
      };
    }
    return stateNode.parent.initial;
  }
  return {
    target: normalizedTarget.map((t) => typeof t === "string" ? getStateNodeByPath(stateNode.parent, t) : t)
  };
}
function isHistoryNode(stateNode) {
  return stateNode.type === "history";
}
function getInitialStateNodesWithTheirAncestors(stateNode) {
  const states = getInitialStateNodes(stateNode);
  for (const initialState of states) {
    for (const ancestor of getProperAncestors(initialState, stateNode)) {
      states.add(ancestor);
    }
  }
  return states;
}
function getInitialStateNodes(stateNode) {
  const set = /* @__PURE__ */ new Set();
  function iter(descStateNode) {
    if (set.has(descStateNode)) {
      return;
    }
    set.add(descStateNode);
    if (descStateNode.type === "compound") {
      iter(descStateNode.initial.target[0]);
    } else if (descStateNode.type === "parallel") {
      for (const child of getChildren(descStateNode)) {
        iter(child);
      }
    }
  }
  iter(stateNode);
  return set;
}
function getStateNode(stateNode, stateKey) {
  if (isStateId(stateKey)) {
    return stateNode.machine.getStateNodeById(stateKey);
  }
  if (!stateNode.states) {
    throw new Error(`Unable to retrieve child state '${stateKey}' from '${stateNode.id}'; no child states exist.`);
  }
  const result = stateNode.states[stateKey];
  if (!result) {
    throw new Error(`Child state '${stateKey}' does not exist on '${stateNode.id}'`);
  }
  return result;
}
function getStateNodeByPath(stateNode, statePath) {
  if (typeof statePath === "string" && isStateId(statePath)) {
    try {
      return stateNode.machine.getStateNodeById(statePath);
    } catch {
    }
  }
  const arrayStatePath = toStatePath(statePath).slice();
  let currentStateNode = stateNode;
  while (arrayStatePath.length) {
    const key = arrayStatePath.shift();
    if (!key.length) {
      break;
    }
    currentStateNode = getStateNode(currentStateNode, key);
  }
  return currentStateNode;
}
function getStateNodes(stateNode, stateValue) {
  if (typeof stateValue === "string") {
    const childStateNode = stateNode.states[stateValue];
    if (!childStateNode) {
      throw new Error(`State '${stateValue}' does not exist on '${stateNode.id}'`);
    }
    return [stateNode, childStateNode];
  }
  const childStateKeys = Object.keys(stateValue);
  const childStateNodes = childStateKeys.map((subStateKey) => getStateNode(stateNode, subStateKey)).filter(Boolean);
  return [stateNode.machine.root, stateNode].concat(childStateNodes, childStateKeys.reduce((allSubStateNodes, subStateKey) => {
    const subStateNode = getStateNode(stateNode, subStateKey);
    if (!subStateNode) {
      return allSubStateNodes;
    }
    const subStateNodes = getStateNodes(subStateNode, stateValue[subStateKey]);
    return allSubStateNodes.concat(subStateNodes);
  }, []));
}
function transitionAtomicNode(stateNode, stateValue, snapshot, event) {
  const childStateNode = getStateNode(stateNode, stateValue);
  const next = childStateNode.next(snapshot, event);
  if (!next || !next.length) {
    return stateNode.next(snapshot, event);
  }
  return next;
}
function transitionCompoundNode(stateNode, stateValue, snapshot, event) {
  const subStateKeys = Object.keys(stateValue);
  const childStateNode = getStateNode(stateNode, subStateKeys[0]);
  const next = transitionNode(childStateNode, stateValue[subStateKeys[0]], snapshot, event);
  if (!next || !next.length) {
    return stateNode.next(snapshot, event);
  }
  return next;
}
function transitionParallelNode(stateNode, stateValue, snapshot, event) {
  const allInnerTransitions = [];
  for (const subStateKey of Object.keys(stateValue)) {
    const subStateValue = stateValue[subStateKey];
    if (!subStateValue) {
      continue;
    }
    const subStateNode = getStateNode(stateNode, subStateKey);
    const innerTransitions = transitionNode(subStateNode, subStateValue, snapshot, event);
    if (innerTransitions) {
      allInnerTransitions.push(...innerTransitions);
    }
  }
  if (!allInnerTransitions.length) {
    return stateNode.next(snapshot, event);
  }
  return allInnerTransitions;
}
function transitionNode(stateNode, stateValue, snapshot, event) {
  if (typeof stateValue === "string") {
    return transitionAtomicNode(stateNode, stateValue, snapshot, event);
  }
  if (Object.keys(stateValue).length === 1) {
    return transitionCompoundNode(stateNode, stateValue, snapshot, event);
  }
  return transitionParallelNode(stateNode, stateValue, snapshot, event);
}
function getHistoryNodes(stateNode) {
  return Object.keys(stateNode.states).map((key) => stateNode.states[key]).filter((sn) => sn.type === "history");
}
function isDescendant(childStateNode, parentStateNode) {
  let marker = childStateNode;
  while (marker.parent && marker.parent !== parentStateNode) {
    marker = marker.parent;
  }
  return marker.parent === parentStateNode;
}
function hasIntersection(s1, s2) {
  const set1 = new Set(s1);
  const set2 = new Set(s2);
  for (const item of set1) {
    if (set2.has(item)) {
      return true;
    }
  }
  for (const item of set2) {
    if (set1.has(item)) {
      return true;
    }
  }
  return false;
}
function removeConflictingTransitions(enabledTransitions, stateNodeSet, historyValue) {
  const filteredTransitions = /* @__PURE__ */ new Set();
  for (const t1 of enabledTransitions) {
    let t1Preempted = false;
    const transitionsToRemove = /* @__PURE__ */ new Set();
    for (const t2 of filteredTransitions) {
      if (hasIntersection(computeExitSet([t1], stateNodeSet, historyValue), computeExitSet([t2], stateNodeSet, historyValue))) {
        if (isDescendant(t1.source, t2.source)) {
          transitionsToRemove.add(t2);
        } else {
          t1Preempted = true;
          break;
        }
      }
    }
    if (!t1Preempted) {
      for (const t3 of transitionsToRemove) {
        filteredTransitions.delete(t3);
      }
      filteredTransitions.add(t1);
    }
  }
  return Array.from(filteredTransitions);
}
function findLeastCommonAncestor(stateNodes) {
  const [head, ...tail] = stateNodes;
  for (const ancestor of getProperAncestors(head, void 0)) {
    if (tail.every((sn) => isDescendant(sn, ancestor))) {
      return ancestor;
    }
  }
}
function getEffectiveTargetStates(transition, historyValue) {
  if (!transition.target) {
    return [];
  }
  const targets = /* @__PURE__ */ new Set();
  for (const targetNode of transition.target) {
    if (isHistoryNode(targetNode)) {
      if (historyValue[targetNode.id]) {
        for (const node of historyValue[targetNode.id]) {
          targets.add(node);
        }
      } else {
        for (const node of getEffectiveTargetStates(resolveHistoryDefaultTransition(targetNode), historyValue)) {
          targets.add(node);
        }
      }
    } else {
      targets.add(targetNode);
    }
  }
  return [...targets];
}
function getTransitionDomain(transition, historyValue) {
  const targetStates = getEffectiveTargetStates(transition, historyValue);
  if (!targetStates) {
    return;
  }
  if (!transition.reenter && targetStates.every((target) => target === transition.source || isDescendant(target, transition.source))) {
    return transition.source;
  }
  const lca = findLeastCommonAncestor(targetStates.concat(transition.source));
  if (lca) {
    return lca;
  }
  if (transition.reenter) {
    return;
  }
  return transition.source.machine.root;
}
function computeExitSet(transitions, stateNodeSet, historyValue) {
  const statesToExit = /* @__PURE__ */ new Set();
  for (const t of transitions) {
    if (t.target?.length) {
      const domain = getTransitionDomain(t, historyValue);
      if (t.reenter && t.source === domain) {
        statesToExit.add(domain);
      }
      for (const stateNode of stateNodeSet) {
        if (isDescendant(stateNode, domain)) {
          statesToExit.add(stateNode);
        }
      }
    }
  }
  return [...statesToExit];
}
function areStateNodeCollectionsEqual(prevStateNodes, nextStateNodeSet) {
  if (prevStateNodes.length !== nextStateNodeSet.size) {
    return false;
  }
  for (const node of prevStateNodes) {
    if (!nextStateNodeSet.has(node)) {
      return false;
    }
  }
  return true;
}
function initialMicrostep(root, preInitialState, actorScope, initEvent, internalQueue) {
  return microstep([{
    target: [...getInitialStateNodes(root)],
    source: root,
    reenter: true,
    actions: [],
    eventType: null,
    toJSON: null
  }], preInitialState, actorScope, initEvent, true, internalQueue);
}
function microstep(transitions, currentSnapshot, actorScope, event, isInitial, internalQueue) {
  const actions = [];
  if (!transitions.length) {
    return [currentSnapshot, actions];
  }
  const originalExecutor = actorScope.actionExecutor;
  actorScope.actionExecutor = (action) => {
    actions.push(action);
    originalExecutor(action);
  };
  try {
    const mutStateNodeSet = new Set(currentSnapshot._nodes);
    let historyValue = currentSnapshot.historyValue;
    const filteredTransitions = removeConflictingTransitions(transitions, mutStateNodeSet, historyValue);
    let nextState = currentSnapshot;
    if (!isInitial) {
      [nextState, historyValue] = exitStates(nextState, event, actorScope, filteredTransitions, mutStateNodeSet, historyValue, internalQueue, actorScope.actionExecutor);
    }
    nextState = resolveActionsAndContext(nextState, event, actorScope, filteredTransitions.flatMap((t) => t.actions), internalQueue, void 0);
    nextState = enterStates(nextState, event, actorScope, filteredTransitions, mutStateNodeSet, internalQueue, historyValue, isInitial);
    const nextStateNodes = [...mutStateNodeSet];
    if (nextState.status === "done") {
      nextState = resolveActionsAndContext(nextState, event, actorScope, nextStateNodes.sort((a, b) => b.order - a.order).flatMap((state) => state.exit), internalQueue, void 0);
    }
    try {
      if (historyValue === currentSnapshot.historyValue && areStateNodeCollectionsEqual(currentSnapshot._nodes, mutStateNodeSet)) {
        return [nextState, actions];
      }
      return [cloneMachineSnapshot(nextState, {
        _nodes: nextStateNodes,
        historyValue
      }), actions];
    } catch (e) {
      throw e;
    }
  } finally {
    actorScope.actionExecutor = originalExecutor;
  }
}
function getMachineOutput(snapshot, event, actorScope, rootNode, rootCompletionNode) {
  if (rootNode.output === void 0) {
    return;
  }
  const doneStateEvent = createDoneStateEvent(rootCompletionNode.id, rootCompletionNode.output !== void 0 && rootCompletionNode.parent ? resolveOutput(rootCompletionNode.output, snapshot.context, event, actorScope.self) : void 0);
  return resolveOutput(rootNode.output, snapshot.context, doneStateEvent, actorScope.self);
}
function enterStates(currentSnapshot, event, actorScope, filteredTransitions, mutStateNodeSet, internalQueue, historyValue, isInitial) {
  let nextSnapshot = currentSnapshot;
  const statesToEnter = /* @__PURE__ */ new Set();
  const statesForDefaultEntry = /* @__PURE__ */ new Set();
  computeEntrySet(filteredTransitions, historyValue, statesForDefaultEntry, statesToEnter);
  if (isInitial) {
    statesForDefaultEntry.add(currentSnapshot.machine.root);
  }
  const completedNodes = /* @__PURE__ */ new Set();
  for (const stateNodeToEnter of [...statesToEnter].sort((a, b) => a.order - b.order)) {
    mutStateNodeSet.add(stateNodeToEnter);
    const actions = [];
    actions.push(...stateNodeToEnter.entry);
    for (const invokeDef of stateNodeToEnter.invoke) {
      actions.push(spawnChild(invokeDef.src, {
        ...invokeDef,
        syncSnapshot: !!invokeDef.onSnapshot
      }));
    }
    if (statesForDefaultEntry.has(stateNodeToEnter)) {
      const initialActions = stateNodeToEnter.initial.actions;
      actions.push(...initialActions);
    }
    nextSnapshot = resolveActionsAndContext(nextSnapshot, event, actorScope, actions, internalQueue, stateNodeToEnter.invoke.map((invokeDef) => invokeDef.id));
    if (stateNodeToEnter.type === "final") {
      const parent = stateNodeToEnter.parent;
      let ancestorMarker = parent?.type === "parallel" ? parent : parent?.parent;
      let rootCompletionNode = ancestorMarker || stateNodeToEnter;
      if (parent?.type === "compound") {
        internalQueue.push(createDoneStateEvent(parent.id, stateNodeToEnter.output !== void 0 ? resolveOutput(stateNodeToEnter.output, nextSnapshot.context, event, actorScope.self) : void 0));
      }
      while (ancestorMarker?.type === "parallel" && !completedNodes.has(ancestorMarker) && isInFinalState(mutStateNodeSet, ancestorMarker)) {
        completedNodes.add(ancestorMarker);
        internalQueue.push(createDoneStateEvent(ancestorMarker.id));
        rootCompletionNode = ancestorMarker;
        ancestorMarker = ancestorMarker.parent;
      }
      if (ancestorMarker) {
        continue;
      }
      nextSnapshot = cloneMachineSnapshot(nextSnapshot, {
        status: "done",
        output: getMachineOutput(nextSnapshot, event, actorScope, nextSnapshot.machine.root, rootCompletionNode)
      });
    }
  }
  return nextSnapshot;
}
function computeEntrySet(transitions, historyValue, statesForDefaultEntry, statesToEnter) {
  for (const t of transitions) {
    const domain = getTransitionDomain(t, historyValue);
    for (const s of t.target || []) {
      if (!isHistoryNode(s) && // if the target is different than the source then it will *definitely* be entered
      (t.source !== s || // we know that the domain can't lie within the source
      // if it's different than the source then it's outside of it and it means that the target has to be entered as well
      t.source !== domain || // reentering transitions always enter the target, even if it's the source itself
      t.reenter)) {
        statesToEnter.add(s);
        statesForDefaultEntry.add(s);
      }
      addDescendantStatesToEnter(s, historyValue, statesForDefaultEntry, statesToEnter);
    }
    const targetStates = getEffectiveTargetStates(t, historyValue);
    for (const s of targetStates) {
      const ancestors = getProperAncestors(s, domain);
      if (domain?.type === "parallel") {
        ancestors.push(domain);
      }
      addAncestorStatesToEnter(statesToEnter, historyValue, statesForDefaultEntry, ancestors, !t.source.parent && t.reenter ? void 0 : domain);
    }
  }
}
function addDescendantStatesToEnter(stateNode, historyValue, statesForDefaultEntry, statesToEnter) {
  if (isHistoryNode(stateNode)) {
    if (historyValue[stateNode.id]) {
      const historyStateNodes = historyValue[stateNode.id];
      for (const s of historyStateNodes) {
        statesToEnter.add(s);
        addDescendantStatesToEnter(s, historyValue, statesForDefaultEntry, statesToEnter);
      }
      for (const s of historyStateNodes) {
        addProperAncestorStatesToEnter(s, stateNode.parent, statesToEnter, historyValue, statesForDefaultEntry);
      }
    } else {
      const historyDefaultTransition = resolveHistoryDefaultTransition(stateNode);
      for (const s of historyDefaultTransition.target) {
        statesToEnter.add(s);
        if (historyDefaultTransition === stateNode.parent?.initial) {
          statesForDefaultEntry.add(stateNode.parent);
        }
        addDescendantStatesToEnter(s, historyValue, statesForDefaultEntry, statesToEnter);
      }
      for (const s of historyDefaultTransition.target) {
        addProperAncestorStatesToEnter(s, stateNode.parent, statesToEnter, historyValue, statesForDefaultEntry);
      }
    }
  } else {
    if (stateNode.type === "compound") {
      const [initialState] = stateNode.initial.target;
      if (!isHistoryNode(initialState)) {
        statesToEnter.add(initialState);
        statesForDefaultEntry.add(initialState);
      }
      addDescendantStatesToEnter(initialState, historyValue, statesForDefaultEntry, statesToEnter);
      addProperAncestorStatesToEnter(initialState, stateNode, statesToEnter, historyValue, statesForDefaultEntry);
    } else {
      if (stateNode.type === "parallel") {
        for (const child of getChildren(stateNode).filter((sn) => !isHistoryNode(sn))) {
          if (![...statesToEnter].some((s) => isDescendant(s, child))) {
            if (!isHistoryNode(child)) {
              statesToEnter.add(child);
              statesForDefaultEntry.add(child);
            }
            addDescendantStatesToEnter(child, historyValue, statesForDefaultEntry, statesToEnter);
          }
        }
      }
    }
  }
}
function addAncestorStatesToEnter(statesToEnter, historyValue, statesForDefaultEntry, ancestors, reentrancyDomain) {
  for (const anc of ancestors) {
    if (!reentrancyDomain || isDescendant(anc, reentrancyDomain)) {
      statesToEnter.add(anc);
    }
    if (anc.type === "parallel") {
      for (const child of getChildren(anc).filter((sn) => !isHistoryNode(sn))) {
        if (![...statesToEnter].some((s) => isDescendant(s, child))) {
          statesToEnter.add(child);
          addDescendantStatesToEnter(child, historyValue, statesForDefaultEntry, statesToEnter);
        }
      }
    }
  }
}
function addProperAncestorStatesToEnter(stateNode, toStateNode, statesToEnter, historyValue, statesForDefaultEntry) {
  addAncestorStatesToEnter(statesToEnter, historyValue, statesForDefaultEntry, getProperAncestors(stateNode, toStateNode));
}
function exitStates(currentSnapshot, event, actorScope, transitions, mutStateNodeSet, historyValue, internalQueue, _actionExecutor) {
  let nextSnapshot = currentSnapshot;
  const statesToExit = computeExitSet(transitions, mutStateNodeSet, historyValue);
  statesToExit.sort((a, b) => b.order - a.order);
  let changedHistory;
  for (const exitStateNode of statesToExit) {
    for (const historyNode of getHistoryNodes(exitStateNode)) {
      let predicate;
      if (historyNode.history === "deep") {
        predicate = (sn) => isAtomicStateNode(sn) && isDescendant(sn, exitStateNode);
      } else {
        predicate = (sn) => {
          return sn.parent === exitStateNode;
        };
      }
      changedHistory ??= {
        ...historyValue
      };
      changedHistory[historyNode.id] = Array.from(mutStateNodeSet).filter(predicate);
    }
  }
  for (const s of statesToExit) {
    nextSnapshot = resolveActionsAndContext(nextSnapshot, event, actorScope, [...s.exit, ...s.invoke.map((def) => stopChild(def.id))], internalQueue, void 0);
    mutStateNodeSet.delete(s);
  }
  return [nextSnapshot, changedHistory || historyValue];
}
function getAction(machine, actionType) {
  return machine.implementations.actions[actionType];
}
function resolveAndExecuteActionsWithContext(currentSnapshot, event, actorScope, actions, extra, retries) {
  const {
    machine
  } = currentSnapshot;
  let intermediateSnapshot = currentSnapshot;
  for (const action of actions) {
    const isInline = typeof action === "function";
    const resolvedAction = isInline ? action : (
      // the existing type of `.actions` assumes non-nullable `TExpressionAction`
      // it's fine to cast this here to get a common type and lack of errors in the rest of the code
      // our logic below makes sure that we call those 2 "variants" correctly
      getAction(machine, typeof action === "string" ? action : action.type)
    );
    const actionArgs = {
      context: intermediateSnapshot.context,
      event,
      self: actorScope.self,
      system: actorScope.system
    };
    const actionParams = isInline || typeof action === "string" ? void 0 : "params" in action ? typeof action.params === "function" ? action.params({
      context: intermediateSnapshot.context,
      event
    }) : action.params : void 0;
    if (!resolvedAction || !("resolve" in resolvedAction)) {
      actorScope.actionExecutor({
        type: typeof action === "string" ? action : typeof action === "object" ? action.type : action.name || "(anonymous)",
        info: actionArgs,
        params: actionParams,
        exec: resolvedAction
      });
      continue;
    }
    const builtinAction = resolvedAction;
    const [nextState, params, actions2] = builtinAction.resolve(
      actorScope,
      intermediateSnapshot,
      actionArgs,
      actionParams,
      resolvedAction,
      // this holds all params
      extra
    );
    intermediateSnapshot = nextState;
    if ("retryResolve" in builtinAction) {
      retries?.push([builtinAction, params]);
    }
    if ("execute" in builtinAction) {
      actorScope.actionExecutor({
        type: builtinAction.type,
        info: actionArgs,
        params,
        exec: builtinAction.execute.bind(null, actorScope, params)
      });
    }
    if (actions2) {
      intermediateSnapshot = resolveAndExecuteActionsWithContext(intermediateSnapshot, event, actorScope, actions2, extra, retries);
    }
  }
  return intermediateSnapshot;
}
function resolveActionsAndContext(currentSnapshot, event, actorScope, actions, internalQueue, deferredActorIds) {
  const retries = deferredActorIds ? [] : void 0;
  const nextState = resolveAndExecuteActionsWithContext(currentSnapshot, event, actorScope, actions, {
    internalQueue,
    deferredActorIds
  }, retries);
  retries?.forEach(([builtinAction, params]) => {
    builtinAction.retryResolve(actorScope, nextState, params);
  });
  return nextState;
}
function macrostep(snapshot, event, actorScope, internalQueue) {
  let nextSnapshot = snapshot;
  const microsteps = [];
  function addMicrostep(step, event2, transitions) {
    actorScope.system._sendInspectionEvent({
      type: "@xstate.microstep",
      actorRef: actorScope.self,
      event: event2,
      snapshot: step[0],
      _transitions: transitions
    });
    microsteps.push(step);
  }
  if (event.type === XSTATE_STOP) {
    nextSnapshot = cloneMachineSnapshot(stopChildren(nextSnapshot, event, actorScope), {
      status: "stopped"
    });
    addMicrostep([nextSnapshot, []], event, []);
    return {
      snapshot: nextSnapshot,
      microsteps
    };
  }
  let nextEvent = event;
  if (nextEvent.type !== XSTATE_INIT) {
    const currentEvent = nextEvent;
    const isErr = isErrorActorEvent(currentEvent);
    const transitions = selectTransitions(currentEvent, nextSnapshot);
    if (isErr && !transitions.length) {
      nextSnapshot = cloneMachineSnapshot(snapshot, {
        status: "error",
        error: currentEvent.error
      });
      addMicrostep([nextSnapshot, []], currentEvent, []);
      return {
        snapshot: nextSnapshot,
        microsteps
      };
    }
    const step = microstep(
      transitions,
      snapshot,
      actorScope,
      nextEvent,
      false,
      // isInitial
      internalQueue
    );
    nextSnapshot = step[0];
    addMicrostep(step, currentEvent, transitions);
  }
  let shouldSelectEventlessTransitions = true;
  const maxIterations = snapshot.machine.options?.maxIterations ?? Infinity;
  let iterationCount = 0;
  while (nextSnapshot.status === "active") {
    iterationCount++;
    if (iterationCount > maxIterations) {
      throw new Error(`Infinite loop detected: the machine has processed more than ${maxIterations} microsteps without reaching a stable state. This usually happens when there's a cycle of transitions (e.g., eventless transitions or raised events causing state A -> B -> C -> A).`);
    }
    let enabledTransitions = shouldSelectEventlessTransitions ? selectEventlessTransitions(nextSnapshot, nextEvent) : [];
    const previousState = enabledTransitions.length ? nextSnapshot : void 0;
    if (!enabledTransitions.length) {
      if (!internalQueue.length) {
        break;
      }
      nextEvent = internalQueue.shift();
      enabledTransitions = selectTransitions(nextEvent, nextSnapshot);
    }
    const step = microstep(enabledTransitions, nextSnapshot, actorScope, nextEvent, false, internalQueue);
    nextSnapshot = step[0];
    shouldSelectEventlessTransitions = nextSnapshot !== previousState;
    addMicrostep(step, nextEvent, enabledTransitions);
  }
  if (nextSnapshot.status !== "active") {
    stopChildren(nextSnapshot, nextEvent, actorScope);
  }
  return {
    snapshot: nextSnapshot,
    microsteps
  };
}
function stopChildren(nextState, event, actorScope) {
  return resolveActionsAndContext(nextState, event, actorScope, Object.values(nextState.children).map((child) => stopChild(child)), [], void 0);
}
function selectTransitions(event, nextState) {
  return nextState.machine.getTransitionData(nextState, event);
}
function selectEventlessTransitions(nextState, event) {
  const enabledTransitionSet = /* @__PURE__ */ new Set();
  const atomicStates = nextState._nodes.filter(isAtomicStateNode);
  for (const stateNode of atomicStates) {
    loop: for (const s of [stateNode].concat(getProperAncestors(stateNode, void 0))) {
      if (!s.always) {
        continue;
      }
      for (const transition of s.always) {
        if (transition.guard === void 0 || evaluateGuard(transition.guard, nextState.context, event, nextState)) {
          enabledTransitionSet.add(transition);
          break loop;
        }
      }
    }
  }
  return removeConflictingTransitions(Array.from(enabledTransitionSet), new Set(nextState._nodes), nextState.historyValue);
}
function resolveStateValue(rootNode, stateValue) {
  const allStateNodes = getAllStateNodes(getStateNodes(rootNode, stateValue));
  return getStateValue(rootNode, [...allStateNodes]);
}
function isMachineSnapshot(value) {
  return !!value && typeof value === "object" && "machine" in value && "value" in value;
}
var machineSnapshotMatches = function matches(testValue) {
  return matchesState(testValue, this.value);
};
var machineSnapshotHasTag = function hasTag(tag) {
  return this.tags.has(tag);
};
var machineSnapshotCan = function can(event) {
  const transitionData = this.machine.getTransitionData(this, event);
  return !!transitionData?.length && // Check that at least one transition is not forbidden
  transitionData.some((t) => t.target !== void 0 || t.actions.length);
};
var machineSnapshotToJSON = function toJSON() {
  const {
    _nodes: nodes,
    tags,
    machine,
    getMeta: getMeta2,
    toJSON: toJSON2,
    can: can2,
    hasTag: hasTag2,
    matches: matches2,
    ...jsonValues
  } = this;
  return {
    ...jsonValues,
    tags: Array.from(tags)
  };
};
var machineSnapshotGetMeta = function getMeta() {
  return this._nodes.reduce((acc, stateNode) => {
    if (stateNode.meta !== void 0) {
      acc[stateNode.id] = stateNode.meta;
    }
    return acc;
  }, {});
};
function createMachineSnapshot(config, machine) {
  return {
    status: config.status,
    output: config.output,
    error: config.error,
    machine,
    context: config.context,
    _nodes: config._nodes,
    value: getStateValue(machine.root, config._nodes),
    tags: new Set(config._nodes.flatMap((sn) => sn.tags)),
    children: config.children,
    historyValue: config.historyValue || {},
    matches: machineSnapshotMatches,
    hasTag: machineSnapshotHasTag,
    can: machineSnapshotCan,
    getMeta: machineSnapshotGetMeta,
    toJSON: machineSnapshotToJSON
  };
}
function cloneMachineSnapshot(snapshot, config = {}) {
  return createMachineSnapshot({
    ...snapshot,
    ...config
  }, snapshot.machine);
}
function serializeHistoryValue(historyValue) {
  if (typeof historyValue !== "object" || historyValue === null) {
    return {};
  }
  const result = {};
  for (const key in historyValue) {
    const value = historyValue[key];
    if (Array.isArray(value)) {
      result[key] = value.map((item) => ({
        id: item.id
      }));
    }
  }
  return result;
}
function getPersistedSnapshot(snapshot, options) {
  const {
    _nodes: nodes,
    tags,
    machine,
    children,
    context,
    can: can2,
    hasTag: hasTag2,
    matches: matches2,
    getMeta: getMeta2,
    toJSON: toJSON2,
    ...jsonValues
  } = snapshot;
  const childrenJson = {};
  for (const id in children) {
    const child = children[id];
    childrenJson[id] = {
      snapshot: child.getPersistedSnapshot(options),
      src: child.src,
      systemId: child.systemId,
      syncSnapshot: child._syncSnapshot
    };
  }
  const persisted = {
    ...jsonValues,
    context: persistContext(context),
    children: childrenJson,
    historyValue: serializeHistoryValue(jsonValues.historyValue)
  };
  return persisted;
}
function persistContext(contextPart) {
  let copy;
  for (const key in contextPart) {
    const value = contextPart[key];
    if (value && typeof value === "object") {
      if ("sessionId" in value && "send" in value && "ref" in value) {
        copy ??= Array.isArray(contextPart) ? contextPart.slice() : {
          ...contextPart
        };
        copy[key] = {
          xstate$$type: $$ACTOR_TYPE,
          id: value.id
        };
      } else {
        const result = persistContext(value);
        if (result !== value) {
          copy ??= Array.isArray(contextPart) ? contextPart.slice() : {
            ...contextPart
          };
          copy[key] = result;
        }
      }
    }
  }
  return copy ?? contextPart;
}
function resolveRaise(_, snapshot, args, actionParams, {
  event: eventOrExpr,
  id,
  delay
}, {
  internalQueue
}) {
  const delaysMap = snapshot.machine.implementations.delays;
  if (typeof eventOrExpr === "string") {
    throw new Error(
      // eslint-disable-next-line @typescript-eslint/restrict-template-expressions
      `Only event objects may be used with raise; use raise({ type: "${eventOrExpr}" }) instead`
    );
  }
  const resolvedEvent = typeof eventOrExpr === "function" ? eventOrExpr(args, actionParams) : eventOrExpr;
  let resolvedDelay;
  if (typeof delay === "string") {
    const configDelay = delaysMap && delaysMap[delay];
    resolvedDelay = typeof configDelay === "function" ? configDelay(args, actionParams) : configDelay;
  } else {
    resolvedDelay = typeof delay === "function" ? delay(args, actionParams) : delay;
  }
  if (typeof resolvedDelay !== "number") {
    internalQueue.push(resolvedEvent);
  }
  return [snapshot, {
    event: resolvedEvent,
    id,
    delay: resolvedDelay
  }, void 0];
}
function executeRaise(actorScope, params) {
  const {
    event,
    delay,
    id
  } = params;
  if (typeof delay === "number") {
    actorScope.defer(() => {
      const self2 = actorScope.self;
      actorScope.system.scheduler.schedule(self2, self2, event, delay, id);
    });
    return;
  }
}
function raise(eventOrExpr, options) {
  function raise2(_args, _params) {
  }
  raise2.type = "xstate.raise";
  raise2.event = eventOrExpr;
  raise2.id = options?.id;
  raise2.delay = options?.delay;
  raise2.resolve = resolveRaise;
  raise2.execute = executeRaise;
  return raise2;
}

// ../../../frontend/node_modules/xstate/dist/assign-29f23f4d.esm.js
function createSpawner(actorScope, {
  machine,
  context
}, event, spawnedChildren) {
  const spawn = (src, options) => {
    if (typeof src === "string") {
      const logic = resolveReferencedActor(machine, src);
      if (!logic) {
        throw new Error(`Actor logic '${src}' not implemented in machine '${machine.id}'`);
      }
      const actorRef = createActor(logic, {
        id: options?.id,
        parent: actorScope.self,
        syncSnapshot: options?.syncSnapshot,
        input: typeof options?.input === "function" ? options.input({
          context,
          event,
          self: actorScope.self
        }) : options?.input,
        src,
        systemId: options?.systemId
      });
      spawnedChildren[actorRef.id] = actorRef;
      return actorRef;
    } else {
      const actorRef = createActor(src, {
        id: options?.id,
        parent: actorScope.self,
        syncSnapshot: options?.syncSnapshot,
        input: options?.input,
        src,
        systemId: options?.systemId
      });
      return actorRef;
    }
  };
  return (src, options) => {
    const actorRef = spawn(src, options);
    spawnedChildren[actorRef.id] = actorRef;
    actorScope.defer(() => {
      if (actorRef._processingStatus === ProcessingStatus.Stopped) {
        return;
      }
      actorRef.start();
    });
    return actorRef;
  };
}
function resolveAssign(actorScope, snapshot, actionArgs, actionParams, {
  assignment
}) {
  if (!snapshot.context) {
    throw new Error("Cannot assign to undefined `context`. Ensure that `context` is defined in the machine config.");
  }
  const spawnedChildren = {};
  const assignArgs = {
    context: snapshot.context,
    event: actionArgs.event,
    spawn: createSpawner(actorScope, snapshot, actionArgs.event, spawnedChildren),
    self: actorScope.self,
    system: actorScope.system
  };
  let partialUpdate = {};
  if (typeof assignment === "function") {
    partialUpdate = assignment(assignArgs, actionParams);
  } else {
    for (const key of Object.keys(assignment)) {
      const propAssignment = assignment[key];
      partialUpdate[key] = typeof propAssignment === "function" ? propAssignment(assignArgs, actionParams) : propAssignment;
    }
  }
  const updatedContext = Object.assign({}, snapshot.context, partialUpdate);
  return [cloneMachineSnapshot(snapshot, {
    context: updatedContext,
    children: Object.keys(spawnedChildren).length ? {
      ...snapshot.children,
      ...spawnedChildren
    } : snapshot.children
  }), void 0, void 0];
}
function assign(assignment) {
  function assign2(_args, _params) {
  }
  assign2.type = "xstate.assign";
  assign2.assignment = assignment;
  assign2.resolve = resolveAssign;
  return assign2;
}

// ../../../frontend/node_modules/xstate/dist/StateMachine-5f345bba.esm.js
var cache = /* @__PURE__ */ new WeakMap();
function memo(object, key, fn) {
  let memoizedData = cache.get(object);
  if (!memoizedData) {
    memoizedData = {
      [key]: fn()
    };
    cache.set(object, memoizedData);
  } else if (!(key in memoizedData)) {
    memoizedData[key] = fn();
  }
  return memoizedData[key];
}
var EMPTY_OBJECT = {};
var toSerializableAction = (action) => {
  if (typeof action === "string") {
    return {
      type: action
    };
  }
  if (typeof action === "function") {
    if ("resolve" in action) {
      return {
        type: action.type
      };
    }
    return {
      type: action.name
    };
  }
  return action;
};
var StateNode = class _StateNode {
  constructor(config, options) {
    this.config = config;
    this.key = void 0;
    this.id = void 0;
    this.type = void 0;
    this.path = void 0;
    this.states = void 0;
    this.history = void 0;
    this.entry = void 0;
    this.exit = void 0;
    this.parent = void 0;
    this.machine = void 0;
    this.meta = void 0;
    this.output = void 0;
    this.order = -1;
    this.description = void 0;
    this.tags = [];
    this.transitions = void 0;
    this.always = void 0;
    this.parent = options._parent;
    this.key = options._key;
    this.machine = options._machine;
    this.path = this.parent ? this.parent.path.concat(this.key) : [];
    this.id = this.config.id || [this.machine.id, ...this.path].join(STATE_DELIMITER);
    this.type = this.config.type || (this.config.states && Object.keys(this.config.states).length ? "compound" : this.config.history ? "history" : "atomic");
    this.description = this.config.description;
    this.order = this.machine.idMap.size;
    this.machine.idMap.set(this.id, this);
    this.states = this.config.states ? mapValues(this.config.states, (stateConfig, key) => {
      const stateNode = new _StateNode(stateConfig, {
        _parent: this,
        _key: key,
        _machine: this.machine
      });
      return stateNode;
    }) : EMPTY_OBJECT;
    if (this.type === "compound" && !this.config.initial) {
      throw new Error(`No initial state specified for compound state node "#${this.id}". Try adding { initial: "${Object.keys(this.states)[0]}" } to the state config.`);
    }
    this.history = this.config.history === true ? "shallow" : this.config.history || false;
    this.entry = toArray(this.config.entry).slice();
    this.exit = toArray(this.config.exit).slice();
    this.meta = this.config.meta;
    this.output = this.type === "final" || !this.parent ? this.config.output : void 0;
    this.tags = toArray(config.tags).slice();
  }
  /** @internal */
  _initialize() {
    this.transitions = formatTransitions(this);
    if (this.config.always) {
      this.always = toTransitionConfigArray(this.config.always).map((t) => formatTransition(this, NULL_EVENT, t));
    }
    Object.keys(this.states).forEach((key) => {
      this.states[key]._initialize();
    });
  }
  /** The well-structured state node definition. */
  get definition() {
    return {
      id: this.id,
      key: this.key,
      version: this.machine.version,
      type: this.type,
      initial: this.initial ? {
        target: this.initial.target,
        source: this,
        actions: this.initial.actions.map(toSerializableAction),
        eventType: null,
        reenter: false,
        toJSON: () => ({
          target: this.initial.target.map((t) => `#${t.id}`),
          source: `#${this.id}`,
          actions: this.initial.actions.map(toSerializableAction),
          eventType: null
        })
      } : void 0,
      history: this.history,
      states: mapValues(this.states, (state) => {
        return state.definition;
      }),
      on: this.on,
      transitions: [...this.transitions.values()].flat().map((t) => ({
        ...t,
        actions: t.actions.map(toSerializableAction)
      })),
      entry: this.entry.map(toSerializableAction),
      exit: this.exit.map(toSerializableAction),
      meta: this.meta,
      order: this.order || -1,
      output: this.output,
      invoke: this.invoke,
      description: this.description,
      tags: this.tags
    };
  }
  /** @internal */
  toJSON() {
    return this.definition;
  }
  /** The logic invoked as actors by this state node. */
  get invoke() {
    return memo(this, "invoke", () => toArray(this.config.invoke).map((invokeConfig, i) => {
      const {
        src,
        systemId
      } = invokeConfig;
      const resolvedId = invokeConfig.id ?? createInvokeId(this.id, i);
      const sourceName = typeof src === "string" ? src : `xstate.invoke.${createInvokeId(this.id, i)}`;
      return {
        ...invokeConfig,
        src: sourceName,
        id: resolvedId,
        systemId,
        toJSON() {
          const {
            onDone,
            onError,
            ...invokeDefValues
          } = invokeConfig;
          return {
            ...invokeDefValues,
            type: "xstate.invoke",
            src: sourceName,
            id: resolvedId
          };
        }
      };
    }));
  }
  /** The mapping of events to transitions. */
  get on() {
    return memo(this, "on", () => {
      const transitions = this.transitions;
      return [...transitions].flatMap(([descriptor, t]) => t.map((t2) => [descriptor, t2])).reduce((map, [descriptor, transition]) => {
        map[descriptor] = map[descriptor] || [];
        map[descriptor].push(transition);
        return map;
      }, {});
    });
  }
  get after() {
    return memo(this, "delayedTransitions", () => getDelayedTransitions(this));
  }
  get initial() {
    return memo(this, "initial", () => formatInitialTransition(this, this.config.initial));
  }
  /** @internal */
  next(snapshot, event) {
    const eventType = event.type;
    const actions = [];
    let selectedTransition;
    const candidates = memo(this, `candidates-${eventType}`, () => getCandidates(this, eventType));
    for (const candidate of candidates) {
      const {
        guard
      } = candidate;
      const resolvedContext = snapshot.context;
      let guardPassed = false;
      try {
        guardPassed = !guard || evaluateGuard(guard, resolvedContext, event, snapshot);
      } catch (err) {
        const guardType = typeof guard === "string" ? guard : typeof guard === "object" ? guard.type : void 0;
        throw new Error(`Unable to evaluate guard ${guardType ? `'${guardType}' ` : ""}in transition for event '${eventType}' in state node '${this.id}':
${err.message}`);
      }
      if (guardPassed) {
        actions.push(...candidate.actions);
        selectedTransition = candidate;
        break;
      }
    }
    return selectedTransition ? [selectedTransition] : void 0;
  }
  /** All the event types accepted by this state node and its descendants. */
  get events() {
    return memo(this, "events", () => {
      const {
        states
      } = this;
      const events = new Set(this.ownEvents);
      if (states) {
        for (const stateId of Object.keys(states)) {
          const state = states[stateId];
          if (state.states) {
            for (const event of state.events) {
              events.add(`${event}`);
            }
          }
        }
      }
      return Array.from(events);
    });
  }
  /**
   * All the events that have transitions directly from this state node.
   *
   * Excludes any inert events.
   */
  get ownEvents() {
    const keys = Object.keys(Object.fromEntries(this.transitions));
    const events = new Set(keys.filter((descriptor) => {
      return this.transitions.get(descriptor).some((transition) => !(!transition.target && !transition.actions.length && !transition.reenter));
    }));
    return Array.from(events);
  }
};
var STATE_IDENTIFIER2 = "#";
var StateMachine = class _StateMachine {
  constructor(config, implementations) {
    this.config = config;
    this.version = void 0;
    this.schemas = void 0;
    this.implementations = void 0;
    this.options = void 0;
    this.__xstatenode = true;
    this.idMap = /* @__PURE__ */ new Map();
    this.root = void 0;
    this.id = void 0;
    this.states = void 0;
    this.events = void 0;
    this.id = config.id || "(machine)";
    this.implementations = {
      actors: implementations?.actors ?? {},
      actions: implementations?.actions ?? {},
      delays: implementations?.delays ?? {},
      guards: implementations?.guards ?? {}
    };
    this.version = this.config.version;
    this.schemas = this.config.schemas;
    this.options = {
      maxIterations: Infinity,
      ...this.config.options
    };
    this.transition = this.transition.bind(this);
    this.getInitialSnapshot = this.getInitialSnapshot.bind(this);
    this.getPersistedSnapshot = this.getPersistedSnapshot.bind(this);
    this.restoreSnapshot = this.restoreSnapshot.bind(this);
    this.start = this.start.bind(this);
    this.root = new StateNode(config, {
      _key: this.id,
      _machine: this
    });
    this.root._initialize();
    formatRouteTransitions(this.root);
    this.states = this.root.states;
    this.events = this.root.events;
  }
  /**
   * Clones this state machine with the provided implementations.
   *
   * @param implementations Options (`actions`, `guards`, `actors`, `delays`) to
   *   recursively merge with the existing options.
   * @returns A new `StateMachine` instance with the provided implementations.
   */
  provide(implementations) {
    const {
      actions,
      guards,
      actors,
      delays
    } = this.implementations;
    return new _StateMachine(this.config, {
      actions: {
        ...actions,
        ...implementations.actions
      },
      guards: {
        ...guards,
        ...implementations.guards
      },
      actors: {
        ...actors,
        ...implementations.actors
      },
      delays: {
        ...delays,
        ...implementations.delays
      }
    });
  }
  resolveState(config) {
    const resolvedStateValue = resolveStateValue(this.root, config.value);
    const nodeSet = getAllStateNodes(getStateNodes(this.root, resolvedStateValue));
    return createMachineSnapshot({
      _nodes: [...nodeSet],
      context: config.context || {},
      children: {},
      status: isInFinalState(nodeSet, this.root) ? "done" : config.status || "active",
      output: config.output,
      error: config.error,
      historyValue: config.historyValue
    }, this);
  }
  /**
   * Determines the next snapshot given the current `snapshot` and received
   * `event`. Calculates a full macrostep from all microsteps.
   *
   * @param snapshot The current snapshot
   * @param event The received event
   */
  transition(snapshot, event, actorScope) {
    return macrostep(snapshot, event, actorScope, []).snapshot;
  }
  /**
   * Determines the next state given the current `state` and `event`. Calculates
   * a microstep.
   *
   * @param state The current state
   * @param event The received event
   */
  microstep(snapshot, event, actorScope) {
    return macrostep(snapshot, event, actorScope, []).microsteps.map(([s]) => s);
  }
  getTransitionData(snapshot, event) {
    return transitionNode(this.root, snapshot.value, snapshot, event) || [];
  }
  /**
   * The initial state _before_ evaluating any microsteps. This "pre-initial"
   * state is provided to initial actions executed in the initial state.
   *
   * @internal
   */
  _getPreInitialState(actorScope, initEvent, internalQueue) {
    const {
      context
    } = this.config;
    const preInitial = createMachineSnapshot({
      context: typeof context !== "function" && context ? context : {},
      _nodes: [this.root],
      children: {},
      status: "active"
    }, this);
    if (typeof context === "function") {
      const assignment = ({
        spawn,
        event,
        self: self2
      }) => context({
        spawn,
        input: event.input,
        self: self2
      });
      return resolveActionsAndContext(preInitial, initEvent, actorScope, [assign(assignment)], internalQueue, void 0);
    }
    return preInitial;
  }
  /**
   * Returns the initial `State` instance, with reference to `self` as an
   * `ActorRef`.
   */
  getInitialSnapshot(actorScope, input) {
    const initEvent = createInitEvent(input);
    const internalQueue = [];
    const preInitialState = this._getPreInitialState(actorScope, initEvent, internalQueue);
    const [nextState] = initialMicrostep(this.root, preInitialState, actorScope, initEvent, internalQueue);
    const {
      snapshot: macroState
    } = macrostep(nextState, initEvent, actorScope, internalQueue);
    return macroState;
  }
  start(snapshot) {
    Object.values(snapshot.children).forEach((child) => {
      if (child.getSnapshot().status === "active") {
        child.start();
      }
    });
  }
  getStateNodeById(stateId) {
    const fullPath = toStatePath(stateId);
    const relativePath = fullPath.slice(1);
    const resolvedStateId = isStateId(fullPath[0]) ? fullPath[0].slice(STATE_IDENTIFIER2.length) : fullPath[0];
    const stateNode = this.idMap.get(resolvedStateId);
    if (!stateNode) {
      throw new Error(`Child state node '#${resolvedStateId}' does not exist on machine '${this.id}'`);
    }
    return getStateNodeByPath(stateNode, relativePath);
  }
  get definition() {
    return this.root.definition;
  }
  toJSON() {
    return this.definition;
  }
  getPersistedSnapshot(snapshot, options) {
    return getPersistedSnapshot(snapshot, options);
  }
  restoreSnapshot(snapshot, _actorScope) {
    const children = {};
    const snapshotChildren = snapshot.children;
    Object.keys(snapshotChildren).forEach((actorId) => {
      const actorData = snapshotChildren[actorId];
      const childState = actorData.snapshot;
      const src = actorData.src;
      const logic = typeof src === "string" ? resolveReferencedActor(this, src) : src;
      if (!logic) {
        return;
      }
      const actorRef = createActor(logic, {
        id: actorId,
        parent: _actorScope.self,
        syncSnapshot: actorData.syncSnapshot,
        snapshot: childState,
        src,
        systemId: actorData.systemId
      });
      children[actorId] = actorRef;
    });
    function resolveHistoryReferencedState(root, referenced) {
      if (referenced instanceof StateNode) {
        return referenced;
      }
      try {
        return root.machine.getStateNodeById(referenced.id);
      } catch {
      }
    }
    function reviveHistoryValue(root, historyValue) {
      if (!historyValue || typeof historyValue !== "object") {
        return {};
      }
      const revived = {};
      for (const key in historyValue) {
        const arr = historyValue[key];
        for (const item of arr) {
          const resolved = resolveHistoryReferencedState(root, item);
          if (!resolved) {
            continue;
          }
          revived[key] ??= [];
          revived[key].push(resolved);
        }
      }
      return revived;
    }
    const revivedHistoryValue = reviveHistoryValue(this.root, snapshot.historyValue);
    const restoredSnapshot = createMachineSnapshot({
      ...snapshot,
      children,
      _nodes: Array.from(getAllStateNodes(getStateNodes(this.root, snapshot.value))),
      historyValue: revivedHistoryValue
    }, this);
    const seen = /* @__PURE__ */ new Set();
    function reviveContext(contextPart, children2) {
      if (seen.has(contextPart)) {
        return;
      }
      seen.add(contextPart);
      for (const key in contextPart) {
        const value = contextPart[key];
        if (value && typeof value === "object") {
          if ("xstate$$type" in value && value.xstate$$type === $$ACTOR_TYPE) {
            contextPart[key] = children2[value.id];
            continue;
          }
          reviveContext(value, children2);
        }
      }
    }
    reviveContext(restoredSnapshot.context, children);
    return restoredSnapshot;
  }
};

// ../../../frontend/node_modules/xstate/dist/log-79409d72.esm.js
function resolveEmit(_, snapshot, args, actionParams, {
  event: eventOrExpr
}) {
  const resolvedEvent = typeof eventOrExpr === "function" ? eventOrExpr(args, actionParams) : eventOrExpr;
  return [snapshot, {
    event: resolvedEvent
  }, void 0];
}
function executeEmit(actorScope, {
  event
}) {
  actorScope.defer(() => actorScope.emit(event));
}
function emit(eventOrExpr) {
  function emit2(_args, _params) {
  }
  emit2.type = "xstate.emit";
  emit2.event = eventOrExpr;
  emit2.resolve = resolveEmit;
  emit2.execute = executeEmit;
  return emit2;
}
var SpecialTargets = /* @__PURE__ */ (function(SpecialTargets2) {
  SpecialTargets2["Parent"] = "#_parent";
  SpecialTargets2["Internal"] = "#_internal";
  return SpecialTargets2;
})({});
function resolveSendTo(actorScope, snapshot, args, actionParams, {
  to,
  event: eventOrExpr,
  id,
  delay
}, extra) {
  const delaysMap = snapshot.machine.implementations.delays;
  if (typeof eventOrExpr === "string") {
    throw new Error(
      // eslint-disable-next-line @typescript-eslint/restrict-template-expressions
      `Only event objects may be used with sendTo; use sendTo({ type: "${eventOrExpr}" }) instead`
    );
  }
  const resolvedEvent = typeof eventOrExpr === "function" ? eventOrExpr(args, actionParams) : eventOrExpr;
  let resolvedDelay;
  if (typeof delay === "string") {
    const configDelay = delaysMap && delaysMap[delay];
    resolvedDelay = typeof configDelay === "function" ? configDelay(args, actionParams) : configDelay;
  } else {
    resolvedDelay = typeof delay === "function" ? delay(args, actionParams) : delay;
  }
  const resolvedTarget = typeof to === "function" ? to(args, actionParams) : to;
  let targetActorRef;
  if (typeof resolvedTarget === "string") {
    if (resolvedTarget === SpecialTargets.Parent) {
      targetActorRef = actorScope.self._parent;
    } else if (resolvedTarget === SpecialTargets.Internal) {
      targetActorRef = actorScope.self;
    } else if (resolvedTarget.startsWith("#_")) {
      targetActorRef = snapshot.children[resolvedTarget.slice(2)];
    } else {
      targetActorRef = extra.deferredActorIds?.includes(resolvedTarget) ? resolvedTarget : snapshot.children[resolvedTarget];
    }
    if (!targetActorRef) {
      throw new Error(`Unable to send event to actor '${resolvedTarget}' from machine '${snapshot.machine.id}'.`);
    }
  } else {
    targetActorRef = resolvedTarget || actorScope.self;
  }
  return [snapshot, {
    to: targetActorRef,
    targetId: typeof resolvedTarget === "string" ? resolvedTarget : void 0,
    event: resolvedEvent,
    id,
    delay: resolvedDelay
  }, void 0];
}
function retryResolveSendTo(_, snapshot, params) {
  if (typeof params.to === "string") {
    params.to = snapshot.children[params.to];
  }
}
function executeSendTo(actorScope, params) {
  actorScope.defer(() => {
    const {
      to,
      event,
      delay,
      id
    } = params;
    if (typeof delay === "number") {
      actorScope.system.scheduler.schedule(actorScope.self, to, event, delay, id);
      return;
    }
    actorScope.system._relay(
      actorScope.self,
      // at this point, in a deferred task, it should already be mutated by retryResolveSendTo
      // if it initially started as a string
      to,
      event.type === XSTATE_ERROR ? createErrorActorEvent(actorScope.self.id, event.data) : event
    );
  });
}
function sendTo(to, eventOrExpr, options) {
  function sendTo2(_args, _params) {
  }
  sendTo2.type = "xstate.sendTo";
  sendTo2.to = to;
  sendTo2.event = eventOrExpr;
  sendTo2.id = options?.id;
  sendTo2.delay = options?.delay;
  sendTo2.resolve = resolveSendTo;
  sendTo2.retryResolve = retryResolveSendTo;
  sendTo2.execute = executeSendTo;
  return sendTo2;
}
function sendParent(event, options) {
  return sendTo(SpecialTargets.Parent, event, options);
}
function resolveEnqueueActions(actorScope, snapshot, args, actionParams, {
  collect
}) {
  const actions = [];
  const enqueue = function enqueue2(action) {
    actions.push(action);
  };
  enqueue.assign = (...args2) => {
    actions.push(assign(...args2));
  };
  enqueue.cancel = (...args2) => {
    actions.push(cancel(...args2));
  };
  enqueue.raise = (...args2) => {
    actions.push(raise(...args2));
  };
  enqueue.sendTo = (...args2) => {
    actions.push(sendTo(...args2));
  };
  enqueue.sendParent = (...args2) => {
    actions.push(sendParent(...args2));
  };
  enqueue.spawnChild = (...args2) => {
    actions.push(spawnChild(...args2));
  };
  enqueue.stopChild = (...args2) => {
    actions.push(stopChild(...args2));
  };
  enqueue.emit = (...args2) => {
    actions.push(emit(...args2));
  };
  collect({
    context: args.context,
    event: args.event,
    enqueue,
    check: (guard) => evaluateGuard(guard, snapshot.context, args.event, snapshot),
    self: actorScope.self,
    system: actorScope.system
  }, actionParams);
  return [snapshot, void 0, actions];
}
function enqueueActions(collect) {
  function enqueueActions2(_args, _params) {
  }
  enqueueActions2.type = "xstate.enqueueActions";
  enqueueActions2.collect = collect;
  enqueueActions2.resolve = resolveEnqueueActions;
  return enqueueActions2;
}
function resolveLog(_, snapshot, actionArgs, actionParams, {
  value,
  label
}) {
  return [snapshot, {
    value: typeof value === "function" ? value(actionArgs, actionParams) : value,
    label
  }, void 0];
}
function executeLog({
  logger
}, {
  value,
  label
}) {
  if (label) {
    logger(label, value);
  } else {
    logger(value);
  }
}
function log(value = ({
  context,
  event
}) => ({
  context,
  event
}), label) {
  function log2(_args, _params) {
  }
  log2.type = "xstate.log";
  log2.value = value;
  log2.label = label;
  log2.resolve = resolveLog;
  log2.execute = executeLog;
  return log2;
}

// ../../../frontend/node_modules/xstate/dist/xstate.esm.js
function createMachine(config, implementations) {
  return new StateMachine(config, implementations);
}
function setup({
  schemas,
  actors,
  actions,
  guards,
  delays
}) {
  return {
    assign,
    sendTo,
    raise,
    log,
    cancel,
    stopChild,
    enqueueActions,
    emit,
    spawnChild,
    createStateConfig: (config) => config,
    createAction: (fn) => fn,
    createMachine: (config) => createMachine({
      ...config,
      schemas
    }, {
      actors,
      actions,
      guards,
      delays
    }),
    extend: (extended) => setup({
      schemas,
      actors,
      actions: {
        ...actions,
        ...extended.actions
      },
      guards: {
        ...guards,
        ...extended.guards
      },
      delays: {
        ...delays,
        ...extended.delays
      }
    })
  };
}

// src/features/prototype/runtime/runtimeCore.ts
var RUNTIME_CORE_VERSION = "0.2.0-spike";
var XSTATE_KERNEL_VERSION = "5.32.4";
var RuntimeCoreError = class extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
    this.name = "RuntimeCoreError";
  }
  code;
};
function requireItem(item, code, message) {
  if (item === void 0) {
    throw new RuntimeCoreError(code, message);
  }
  return item;
}
function valueMatchesType(value, expected, nullable) {
  if (value.type === "null") {
    return nullable;
  }
  return value.type === expected;
}
function entityRefMatchesSchema(value, entitySchemaId) {
  return value.type !== "entityRef" || value.schemaId === entitySchemaId;
}
function cloneRuntimeValue(value) {
  return { ...value };
}
function cloneFieldValues(values) {
  return values.map((entry) => ({ fieldId: entry.fieldId, value: cloneRuntimeValue(entry.value) }));
}
function cloneEntity(entity) {
  return { id: entity.id, schemaId: entity.schemaId, fields: cloneFieldValues(entity.fields) };
}
function cloneState(state) {
  return {
    ...state,
    navigationStack: [...state.navigationStack],
    variableValues: state.variableValues.map((entry) => ({
      variableId: entry.variableId,
      value: cloneRuntimeValue(entry.value)
    })),
    entitySets: state.entitySets.map((set) => ({
      schemaId: set.schemaId,
      entities: set.entities.map(cloneEntity)
    })),
    formStates: state.formStates.map((form) => ({
      formId: form.formId,
      values: cloneFieldValues(form.values),
      errors: form.errors.map((error) => ({ ...error }))
    })),
    notifications: state.notifications.map((notification) => ({ ...notification }))
  };
}
function requireFormState(state, formId) {
  return requireItem(
    state.formStates.find((form) => form.formId === formId),
    "runtime_form_state_missing",
    `Runtime form state ${formId} does not exist`
  );
}
function requireFieldValue(values, fieldId) {
  return requireItem(
    values.find((entry) => entry.fieldId === fieldId),
    "runtime_field_value_missing",
    `Runtime field value ${fieldId} does not exist`
  ).value;
}
function requireVariableValue(state, variableId) {
  return requireItem(
    state.variableValues.find((entry) => entry.variableId === variableId),
    "runtime_variable_value_missing",
    `Runtime variable ${variableId} does not exist`
  ).value;
}
function requireEntitySet(state, schemaId) {
  return requireItem(
    state.entitySets.find((set) => set.schemaId === schemaId),
    "runtime_entity_set_missing",
    `Runtime entity set ${schemaId} does not exist`
  );
}
function resolveEntityRef(state, expression, event) {
  const value = evaluateValueExpression(state, expression, event);
  if (value.type !== "entityRef") {
    throw new RuntimeCoreError(
      "runtime_entity_ref_required",
      "Expression did not resolve to entityRef"
    );
  }
  return value;
}
function evaluateValueExpression(state, expression, event) {
  switch (expression.kind) {
    case "literal":
      return cloneRuntimeValue(expression.value);
    case "variable":
      return cloneRuntimeValue(requireVariableValue(state, expression.variableId));
    case "formField":
      return cloneRuntimeValue(
        requireFieldValue(requireFormState(state, expression.formId).values, expression.fieldId)
      );
    case "eventEntityRef":
      if (event.kind !== "tableRowActivated") {
        throw new RuntimeCoreError(
          "runtime_event_entity_ref_missing",
          "Current runtime event has no entity reference"
        );
      }
      return cloneRuntimeValue(event.entityRef);
    case "entityField": {
      const referenceValue = evaluateValueExpression(state, expression.entityRef, event);
      if (referenceValue.type === "null") {
        return cloneRuntimeValue(expression.fallback);
      }
      if (referenceValue.type !== "entityRef") {
        throw new RuntimeCoreError(
          "runtime_entity_ref_required",
          "Entity field expression did not resolve to entityRef"
        );
      }
      const entityRef = referenceValue;
      const entity = requireItem(
        requireEntitySet(state, entityRef.schemaId).entities.find(
          (candidate) => candidate.id === entityRef.entityId
        ),
        "runtime_entity_missing",
        `Runtime entity ${entityRef.entityId} does not exist`
      );
      return cloneRuntimeValue(requireFieldValue(entity.fields, expression.fieldId));
    }
  }
}
function runtimeValuesEqual(left, right) {
  if (left.type !== right.type) {
    return false;
  }
  switch (left.type) {
    case "null":
      return true;
    case "boolean":
      return right.type === "boolean" && left.value === right.value;
    case "integer":
      return right.type === "integer" && left.value === right.value;
    case "string":
      return right.type === "string" && left.value === right.value;
    case "enum":
      return right.type === "enum" && left.value === right.value;
    case "entityRef":
      return right.type === "entityRef" && left.schemaId === right.schemaId && left.entityId === right.entityId;
  }
}
function validateForm(definition, state, formId) {
  const formDefinition = requireItem(
    definition.forms.find((form) => form.id === formId),
    "runtime_form_definition_missing",
    `Runtime form definition ${formId} does not exist`
  );
  const formState = requireFormState(state, formId);
  const errors = [];
  for (const field of formDefinition.fields) {
    const value = requireFieldValue(formState.values, field.id);
    if (field.valueType !== value.type) {
      errors.push({ fieldId: field.id, code: "type_mismatch" });
      continue;
    }
    if (field.required && value.type === "string" && value.value.trim().length === 0) {
      errors.push({ fieldId: field.id, code: "required" });
    }
    if (field.required && value.type === "integer" && field.minInteger !== null && value.value < field.minInteger) {
      errors.push({ fieldId: field.id, code: "min_integer" });
    }
  }
  return errors;
}
function evaluatePredicate(definition, state, predicate, event) {
  switch (predicate.kind) {
    case "all":
      return predicate.items.every((item) => evaluatePredicate(definition, state, item, event));
    case "roleIs":
      return state.actorRoleId === predicate.roleId;
    case "formValid":
      return validateForm(definition, state, predicate.formId).length === 0;
    case "compare": {
      const equal = runtimeValuesEqual(
        evaluateValueExpression(state, predicate.left, event),
        evaluateValueExpression(state, predicate.right, event)
      );
      return predicate.operator === "eq" ? equal : !equal;
    }
  }
}
function replaceVariableValue(definition, state, variableId, value) {
  const variable = requireItem(
    definition.variables.find((candidate) => candidate.id === variableId),
    "runtime_variable_definition_missing",
    `Unknown variable definition ${variableId}`
  );
  if (!valueMatchesType(value, variable.valueType, variable.nullable)) {
    throw new RuntimeCoreError(
      "runtime_variable_type_mismatch",
      `Variable ${variableId} requires ${variable.valueType}`
    );
  }
  if (!entityRefMatchesSchema(value, variable.entitySchemaId)) {
    throw new RuntimeCoreError(
      "runtime_variable_entity_schema_mismatch",
      `Variable ${variableId} requires entity schema ${variable.entitySchemaId}`
    );
  }
  let replaced = false;
  const variableValues = state.variableValues.map((entry) => {
    if (entry.variableId !== variableId) {
      return entry;
    }
    replaced = true;
    return { variableId, value: cloneRuntimeValue(value) };
  });
  if (!replaced) {
    throw new RuntimeCoreError("runtime_variable_value_missing", `Unknown variable ${variableId}`);
  }
  return { ...state, variableValues };
}
function replaceFormState(state, formId, replacement) {
  return {
    ...state,
    formStates: state.formStates.map((form) => form.formId === formId ? replacement : form)
  };
}
function replaceEntitySet(state, schemaId, replacement) {
  return {
    ...state,
    entitySets: state.entitySets.map((set) => set.schemaId === schemaId ? replacement : set)
  };
}
function requireAllocation(allocations, key) {
  return requireItem(
    allocations.find((allocation) => allocation.key === key),
    "runtime_entity_allocation_missing",
    `Runtime entity allocation ${key} does not exist`
  ).entityId;
}
function applyEffect(definition, state, event, effect, eventIndex, branch, effectIndex, allocations) {
  switch (effect.kind) {
    case "setVariable":
      return {
        state: replaceVariableValue(
          definition,
          state,
          effect.variableId,
          evaluateValueExpression(state, effect.value, event)
        ),
        stop: false,
        outcome: "applied"
      };
    case "validateForm": {
      const errors = validateForm(definition, state, effect.formId);
      const form = requireFormState(state, effect.formId);
      const nextState = replaceFormState(state, effect.formId, { ...form, errors });
      return {
        state: nextState,
        stop: errors.length > 0,
        outcome: errors.length > 0 ? "validation_failed" : "applied"
      };
    }
    case "createEntity": {
      const entityId = requireAllocation(allocations, `${eventIndex}:${branch}:${effectIndex}`);
      const schema = requireItem(
        definition.entitySchemas.find((candidate) => candidate.id === effect.schemaId),
        "runtime_entity_schema_missing",
        `Runtime schema ${effect.schemaId} does not exist`
      );
      const fields = schema.fields.map((field) => {
        const assignment = requireItem(
          effect.values.find((candidate) => candidate.fieldId === field.id),
          "runtime_entity_field_assignment_missing",
          `Create effect is missing field ${field.id}`
        );
        const value = evaluateValueExpression(state, assignment.value, event);
        if (!valueMatchesType(value, field.valueType, field.nullable)) {
          throw new RuntimeCoreError(
            "runtime_entity_field_type_mismatch",
            `Entity field ${field.id} value does not match ${field.valueType}`
          );
        }
        return { fieldId: field.id, value };
      });
      const set = requireEntitySet(state, effect.schemaId);
      const withEntity = replaceEntitySet(state, effect.schemaId, {
        ...set,
        entities: [...set.entities, { id: entityId, schemaId: effect.schemaId, fields }]
      });
      return {
        state: replaceVariableValue(definition, withEntity, effect.resultVariableId, {
          type: "entityRef",
          schemaId: effect.schemaId,
          entityId
        }),
        stop: false,
        outcome: "applied"
      };
    }
    case "updateEntity": {
      const entityRef = resolveEntityRef(state, effect.entityRef, event);
      if (entityRef.schemaId !== effect.schemaId) {
        throw new RuntimeCoreError(
          "runtime_entity_schema_mismatch",
          `Entity ref schema ${entityRef.schemaId} does not match ${effect.schemaId}`
        );
      }
      const schema = requireItem(
        definition.entitySchemas.find((candidate) => candidate.id === effect.schemaId),
        "runtime_entity_schema_missing",
        `Runtime schema ${effect.schemaId} does not exist`
      );
      const set = requireEntitySet(state, effect.schemaId);
      let found = false;
      const entities = set.entities.map((entity) => {
        if (entity.id !== entityRef.entityId) {
          return entity;
        }
        found = true;
        const fields = entity.fields.map((fieldValue) => {
          const update = effect.updates.find(
            (candidate) => candidate.fieldId === fieldValue.fieldId
          );
          if (update === void 0) {
            return fieldValue;
          }
          const field = requireItem(
            schema.fields.find((candidate) => candidate.id === update.fieldId),
            "runtime_entity_field_missing",
            `Runtime field ${update.fieldId} does not exist`
          );
          const value = evaluateValueExpression(state, update.value, event);
          if (!valueMatchesType(value, field.valueType, field.nullable)) {
            throw new RuntimeCoreError(
              "runtime_entity_field_type_mismatch",
              `Entity field ${field.id} value does not match ${field.valueType}`
            );
          }
          return { fieldId: fieldValue.fieldId, value };
        });
        return { ...entity, fields };
      });
      if (!found) {
        throw new RuntimeCoreError(
          "runtime_entity_missing",
          `Runtime entity ${entityRef.entityId} does not exist`
        );
      }
      return {
        state: replaceEntitySet(state, effect.schemaId, { ...set, entities }),
        stop: false,
        outcome: "applied"
      };
    }
    case "navigate": {
      if (!definition.pageIds.includes(effect.targetPageId)) {
        throw new RuntimeCoreError(
          "runtime_page_missing",
          `Runtime page ${effect.targetPageId} does not exist`
        );
      }
      return {
        state: {
          ...state,
          currentPageId: effect.targetPageId,
          navigationStack: state.currentPageId === effect.targetPageId ? state.navigationStack : [...state.navigationStack, state.currentPageId]
        },
        stop: false,
        outcome: "applied"
      };
    }
    case "notify":
      return {
        state: {
          ...state,
          notifications: [
            ...state.notifications,
            {
              id: `${state.sessionId}:${state.sequenceNo + 1}:${eventIndex}:${effectIndex}`,
              level: effect.level,
              message: effect.message
            }
          ]
        },
        stop: false,
        outcome: "applied"
      };
  }
}
function runtimeNodeEventIdentity(event) {
  switch (event.kind) {
    case "nodeActivated":
      return { nodeId: event.nodeId, event: event.event };
    case "tableRowActivated":
      return { nodeId: event.nodeId, event: "rowActivated" };
    case "fieldValueCommitted":
    case "switchSimulatedRole":
      return null;
  }
}
function findRuleForEvent(definition, event) {
  const identity2 = runtimeNodeEventIdentity(event);
  if (identity2 === null) {
    return null;
  }
  const matches2 = definition.rules.filter(
    (rule) => rule.enabled && rule.trigger.kind === "nodeEvent" && rule.trigger.nodeId === identity2.nodeId && rule.trigger.event === identity2.event
  );
  if (matches2.length > 1) {
    throw new RuntimeCoreError(
      "runtime_rule_ambiguous",
      `Multiple runtime rules match node ${identity2.nodeId} event ${identity2.event}`
    );
  }
  return matches2[0] ?? null;
}
function assertTableRowVisible(definition, state, event) {
  if (event.kind !== "tableRowActivated") {
    return;
  }
  const viewModel = deriveRuntimeViewModel(definition, state);
  const rows = viewModel.nodes.find((node) => node.nodeId === event.nodeId)?.properties.find((property) => property.target === "tableRows");
  if (rows?.target !== "tableRows") {
    throw new RuntimeCoreError(
      "runtime_table_binding_missing",
      `Runtime table ${event.nodeId} has no rows binding`
    );
  }
  const visible = rows.rows.some(
    (entity) => entity.id === event.entityRef.entityId && entity.schemaId === event.entityRef.schemaId
  );
  if (!visible) {
    throw new RuntimeCoreError(
      "runtime_table_entity_not_visible",
      `Runtime entity ${event.entityRef.entityId} is not visible in table ${event.nodeId}`
    );
  }
}
function applyFieldValueEvent(definition, state, event) {
  if (event.kind !== "fieldValueCommitted") {
    return state;
  }
  const formDefinition = requireItem(
    definition.forms.find((form2) => form2.id === event.formId),
    "runtime_form_definition_missing",
    `Runtime form definition ${event.formId} does not exist`
  );
  const field = requireItem(
    formDefinition.fields.find((candidate) => candidate.id === event.fieldId),
    "runtime_form_field_missing",
    `Runtime form field ${event.fieldId} does not exist`
  );
  if (event.value.type !== field.valueType) {
    throw new RuntimeCoreError(
      "runtime_form_field_type_mismatch",
      `Runtime form field ${event.fieldId} requires ${field.valueType}`
    );
  }
  const form = requireFormState(state, event.formId);
  return replaceFormState(state, event.formId, {
    ...form,
    values: form.values.map(
      (entry) => entry.fieldId === event.fieldId ? { ...entry, value: cloneRuntimeValue(event.value) } : entry
    ),
    errors: form.errors.filter((error) => error.fieldId !== event.fieldId)
  });
}
function applyRoleSwitchEvent(definition, state, event) {
  if (event.kind !== "switchSimulatedRole") {
    return state;
  }
  if (!state.allowSimulatedRoleSwitch) {
    throw new RuntimeCoreError(
      "runtime_role_switch_forbidden",
      "Runtime scenario does not allow simulated role switching"
    );
  }
  if (!definition.roles.some((role) => role.id === event.roleId)) {
    throw new RuntimeCoreError(
      "runtime_role_missing",
      `Runtime role ${event.roleId} does not exist`
    );
  }
  return { ...state, actorRoleId: event.roleId };
}
function applyRuleEffects(definition, state, event, eventIndex, branch, effects, allocations, traces) {
  let current = state;
  let outcome = "applied";
  for (const [effectIndex, effect] of effects.entries()) {
    const beforeState = cloneState(current);
    const result = applyEffect(
      definition,
      current,
      event,
      effect,
      eventIndex,
      branch,
      effectIndex,
      allocations
    );
    current = result.state;
    outcome = result.outcome;
    traces.push({
      eventIndex,
      effectIndex,
      effectKind: effect.kind,
      beforeState,
      afterState: cloneState(current)
    });
    if (result.stop) {
      return { state: current, stop: true, outcome };
    }
  }
  return { state: current, stop: false, outcome };
}
function reduceEventBatch(definition, baseState, batch, allocations) {
  let state = cloneState(baseState);
  let outcome = "applied";
  const matchedRuleIds = [];
  const effectTraces = [];
  for (const [eventIndex, event] of batch.events.entries()) {
    state = applyFieldValueEvent(definition, state, event);
    state = applyRoleSwitchEvent(definition, state, event);
    const identity2 = runtimeNodeEventIdentity(event);
    const rule = findRuleForEvent(definition, event);
    if (identity2 === null) {
      continue;
    }
    if (rule === null) {
      throw new RuntimeCoreError(
        "runtime_rule_missing",
        `No runtime rule matches node ${identity2.nodeId}`
      );
    }
    assertTableRowVisible(definition, state, event);
    matchedRuleIds.push(rule.id);
    const guardPasses = rule.guard === null || evaluatePredicate(definition, state, rule.guard, event);
    const branch = guardPasses ? "effects" : "guardFalseEffects";
    const effects = rule[branch];
    if (!guardPasses) {
      outcome = "guard_false";
    }
    const effectResult = applyRuleEffects(
      definition,
      state,
      event,
      eventIndex,
      branch,
      effects,
      allocations,
      effectTraces
    );
    state = effectResult.state;
    if (effectResult.outcome === "validation_failed") {
      outcome = "validation_failed";
    }
    if (effectResult.stop) {
      break;
    }
  }
  return {
    state: { ...state, sequenceNo: baseState.sequenceNo + 1 },
    outcome,
    matchedRuleIds,
    effectTraces
  };
}
var runtimeMachine = setup({
  types: {
    context: {},
    events: {},
    input: {}
  },
  actions: {
    applyRuntimeEventBatch: assign(({ context, event }) => {
      const reduction = reduceEventBatch(
        context.definition,
        context.state,
        event.batch,
        event.allocations
      );
      return { ...context, state: reduction.state, reduction };
    })
  }
}).createMachine({
  id: "prototype-runtime",
  initial: "ready",
  context: ({ input }) => ({ ...input, reduction: null }),
  states: {
    ready: {
      on: {
        "runtime.eventBatch": {
          actions: "applyRuntimeEventBatch"
        }
      }
    }
  }
});
function compareRuntimeValues(left, right) {
  if (left.type !== right.type) {
    return left.type < right.type ? -1 : 1;
  }
  switch (left.type) {
    case "null":
      return 0;
    case "boolean": {
      if (right.type !== "boolean" || left.value === right.value) return 0;
      return left.value ? 1 : -1;
    }
    case "integer": {
      if (right.type !== "integer" || left.value === right.value) return 0;
      return left.value < right.value ? -1 : 1;
    }
    case "string": {
      if (right.type !== "string" || left.value === right.value) return 0;
      return left.value < right.value ? -1 : 1;
    }
    case "enum": {
      if (right.type !== "enum" || left.value === right.value) return 0;
      return left.value < right.value ? -1 : 1;
    }
    case "entityRef": {
      if (right.type !== "entityRef") return 0;
      const leftKey = `${left.schemaId}:${left.entityId}`;
      const rightKey = `${right.schemaId}:${right.entityId}`;
      if (leftKey === rightKey) return 0;
      return leftKey < rightKey ? -1 : 1;
    }
  }
}
function deriveRuntimeViewModel(definition, state) {
  const byNode = /* @__PURE__ */ new Map();
  const placeholderEvent = {
    kind: "switchSimulatedRole",
    roleId: state.actorRoleId
  };
  for (const binding of definition.viewBindings) {
    const existing = byNode.get(binding.nodeId) ?? [];
    let property;
    switch (binding.target) {
      case "textContent":
        property = {
          target: "textContent",
          value: evaluateValueExpression(state, binding.value, placeholderEvent)
        };
        break;
      case "visibility":
        property = {
          target: "visibility",
          value: {
            type: "boolean",
            value: evaluatePredicate(definition, state, binding.predicate, placeholderEvent)
          }
        };
        break;
      case "tableRows": {
        const set = requireEntitySet(state, binding.schemaId);
        const rows = set.entities.map(cloneEntity);
        const sortFieldId = binding.sortFieldId;
        if (sortFieldId !== null) {
          rows.sort((left, right) => {
            const compared = compareRuntimeValues(
              requireFieldValue(left.fields, sortFieldId),
              requireFieldValue(right.fields, sortFieldId)
            );
            return binding.sortDirection === "asc" ? compared : -compared;
          });
        }
        property = { target: "tableRows", rows };
        break;
      }
    }
    byNode.set(binding.nodeId, [...existing, property]);
  }
  const nodes = Array.from(byNode, ([nodeId, properties]) => ({
    nodeId,
    properties: [...properties].sort((left, right) => {
      if (left.target === right.target) return 0;
      return left.target < right.target ? -1 : 1;
    })
  })).sort((left, right) => {
    if (left.nodeId === right.nodeId) return 0;
    return left.nodeId < right.nodeId ? -1 : 1;
  });
  return { nodes };
}

// src/features/prototype/runtime/runtimeBuildIdentity.ts
var RUNTIME_CORE_SOURCE_HASH = "sha256:2ea354a6f2e11b0511fffb3da8ac434cd5ea4d5a70c77546ec5daf2d19f5097a";

// src/features/prototype/structured/structuredPrototypeNodes.ts
function isStructuredPrototypeContainerNode(node) {
  return node.type === "Stack" || node.type === "Grid" || node.type === "Form" || node.type === "Freeform";
}

// src/features/prototype/structured/prototypeRendererCore.ts
var PROTOTYPE_RENDERER_VERSION = "structured-prototype-renderer/0.2.0";
var PROTOTYPE_RENDERER_ENVIRONMENT_VERSION = "node20-static-bundle/1";
var PROTOTYPE_RENDERER_SANDBOX_POLICY_VERSION = "prototype-static-csp/1";
var PrototypeRendererError = class extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
    this.name = "PrototypeRendererError";
  }
  code;
};
function escapeHtml(value) {
  return value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}
function length(value) {
  if (value.unit === "auto") return "auto";
  if (value.value === null) {
    throw new PrototypeRendererError("renderer_layout_invalid", "non-auto length has no value");
  }
  const suffix = value.unit === "percent" ? "%" : value.unit;
  return `${value.value}${suffix}`;
}
var CSS_COLOR_KEYWORDS = /* @__PURE__ */ new Set([
  "aqua",
  "black",
  "blue",
  "brown",
  "currentcolor",
  "cyan",
  "fuchsia",
  "gray",
  "green",
  "grey",
  "lime",
  "magenta",
  "maroon",
  "navy",
  "olive",
  "orange",
  "pink",
  "purple",
  "red",
  "rebeccapurple",
  "silver",
  "teal",
  "transparent",
  "white",
  "yellow"
]);
function safeColorTokenValue(value) {
  if (value !== value.trim() || value.length === 0 || /[;{}@'"\\\r\n\f]/u.test(value) || /\/\*|\*\//u.test(value) || /\b(?:url|var)\s*\(/iu.test(value)) {
    return false;
  }
  if (/^#(?:[0-9a-f]{3}|[0-9a-f]{4}|[0-9a-f]{6}|[0-9a-f]{8})$/iu.test(value)) {
    return true;
  }
  if (CSS_COLOR_KEYWORDS.has(value.toLowerCase())) return true;
  return /^(?:rgb|rgba|hsl|hsla|oklab|oklch|lab|lch|color)\([0-9a-z.+,%/ \t-]+\)$/iu.test(value);
}
function safeTokenValue(kind, value) {
  const valid = kind === "color" ? safeColorTokenValue(value) : /^(?:0|[1-9][0-9]*(?:\.[0-9]{1,4})?)(?:px|rem)$/u.test(value);
  if (!valid) {
    throw new PrototypeRendererError(
      "renderer_token_unsupported",
      `renderer does not support ${kind} token value ${value}`
    );
  }
  return value;
}
function readableTextColor(value, fallback) {
  const match = /^#([0-9a-f]{3}|[0-9a-f]{4}|[0-9a-f]{6}|[0-9a-f]{8})$/iu.exec(value);
  if (match === null) return fallback;
  const hex = match[1];
  if (hex === void 0) return fallback;
  const expanded = hex.length === 3 || hex.length === 4 ? hex.slice(0, 3).split("").map((character) => `${character}${character}`).join("") : hex.slice(0, 6);
  const red = Number.parseInt(expanded.slice(0, 2), 16);
  const green = Number.parseInt(expanded.slice(2, 4), 16);
  const blue = Number.parseInt(expanded.slice(4, 6), 16);
  return (red * 299 + green * 587 + blue * 114) / 1e3 >= 150 ? "#17201d" : "#ffffff";
}
function shellColorToken(document, key) {
  const token = document.tokens.colors.find((candidate) => candidate.key === key);
  if (token === void 0) {
    throw new PrototypeRendererError(
      "renderer_shell_token_missing",
      `prototype shell references unknown color token ${key}`
    );
  }
  return safeTokenValue("color", token.value);
}
function resolvePrototypeShellTheme(document) {
  const dark = document.settings.theme === "dark";
  const fallbackText = dark ? "#ffffff" : "#17201d";
  const shell = document.settings.shell;
  const accent = shellColorToken(document, shell.accentColorTokenKey);
  const navigationBackground = shellColorToken(document, shell.navigationBackgroundColorTokenKey);
  const contentBackground = shellColorToken(document, shell.contentBackgroundColorTokenKey);
  const surface = shellColorToken(document, shell.surfaceColorTokenKey);
  return {
    accent,
    accentText: readableTextColor(accent, fallbackText),
    navigationBackground,
    navigationText: readableTextColor(navigationBackground, fallbackText),
    contentBackground,
    contentText: readableTextColor(contentBackground, fallbackText),
    surface,
    surfaceText: readableTextColor(surface, fallbackText)
  };
}
function structuredPrototypeShowsRoleControl(document) {
  return document.runtime.roles.length > 1 && document.runtime.scenarios[0]?.allowSimulatedRoleSwitch === true;
}
function layoutRules(node) {
  const item = node.layoutItem;
  const rules = [
    `width:${length(item.width)}`,
    `height:${length(item.height)}`,
    `flex-grow:${item.grow}`,
    `flex-shrink:${item.shrink}`,
    `align-self:${item.alignSelf === "auto" ? "auto" : item.alignSelf}`
  ];
  if (item.minWidth !== null) rules.push(`min-width:${length(item.minWidth)}`);
  if (item.maxWidth !== null) rules.push(`max-width:${length(item.maxWidth)}`);
  if (item.minHeight !== null) rules.push(`min-height:${length(item.minHeight)}`);
  if (item.maxHeight !== null) rules.push(`max-height:${length(item.maxHeight)}`);
  if (item.position !== void 0) {
    rules.push("position:absolute", `left:${item.position.x}px`, `top:${item.position.y}px`);
  }
  if (node.visibility === "hidden") rules.push("display:none");
  if (isStructuredPrototypeContainerNode(node) && item.position === void 0) {
    rules.push("position:relative");
  }
  if (node.type === "Freeform") {
    rules.push("overflow:hidden");
  }
  if (node.type === "Stack") {
    rules.push(
      "display:flex",
      `flex-direction:${node.direction}`,
      `gap:${node.gap}px`,
      `align-items:${node.align}`,
      `justify-content:${node.justify === "between" ? "space-between" : node.justify}`,
      `padding:${node.padding.top}px ${node.padding.right}px ${node.padding.bottom}px ${node.padding.left}px`
    );
  }
  if (node.type === "Grid") {
    rules.push(
      "display:grid",
      `grid-template-columns:repeat(${node.columns},minmax(0,1fr))`,
      `gap:${node.gap}px`,
      `padding:${node.padding.top}px ${node.padding.right}px ${node.padding.bottom}px ${node.padding.left}px`
    );
  }
  if (node.type === "Form") {
    rules.push(
      "display:flex",
      "flex-direction:column",
      `gap:${node.gap}px`,
      `padding:${node.padding.top}px ${node.padding.right}px ${node.padding.bottom}px ${node.padding.left}px`
    );
  }
  if (node.type === "Divider") {
    rules.push(
      "height:1px",
      `margin:${node.spacing}px 0`,
      `background:${node.tone === "muted" ? "#e6eae8" : "#c9d2ce"}`
    );
  }
  if (node.type === "Badge") {
    const tones = {
      default: ["#eef1ef", "#39443f"],
      success: ["#e9f4ec", "#237a45"],
      warning: ["#fff2d8", "#936221"],
      danger: ["#fff1f3", "#8c1d31"]
    };
    const [background, color] = tones[node.tone];
    rules.push(
      "display:inline-flex",
      "width:fit-content",
      "align-items:center",
      "gap:4px",
      "padding:2px 8px",
      "font-size:11px",
      "font-weight:700",
      "line-height:1.5",
      `background:${background}`,
      `color:${color}`
    );
  }
  return rules;
}
function responsiveRules(node) {
  const widths = { sm: 640, md: 768, lg: 1024 };
  return node.responsive.map((override) => {
    const rules = [];
    const item = override.layoutItem;
    if (item.width !== void 0) rules.push(`width:${length(item.width)}`);
    if (item.minWidth !== void 0) {
      rules.push(item.minWidth === null ? "min-width:0" : `min-width:${length(item.minWidth)}`);
    }
    if (item.maxWidth !== void 0) {
      rules.push(item.maxWidth === null ? "max-width:none" : `max-width:${length(item.maxWidth)}`);
    }
    if (item.height !== void 0) rules.push(`height:${length(item.height)}`);
    if (item.minHeight !== void 0) {
      rules.push(item.minHeight === null ? "min-height:0" : `min-height:${length(item.minHeight)}`);
    }
    if (item.maxHeight !== void 0) {
      rules.push(
        item.maxHeight === null ? "max-height:none" : `max-height:${length(item.maxHeight)}`
      );
    }
    if (item.grow !== void 0) rules.push(`flex-grow:${item.grow}`);
    if (item.shrink !== void 0) rules.push(`flex-shrink:${item.shrink}`);
    if (item.alignSelf !== void 0) rules.push(`align-self:${item.alignSelf}`);
    return `@media(min-width:${widths[override.breakpoint]}px){[data-prototype-node-id="${node.id}"]{${rules.join(";")}}}`;
  });
}
function gridColumnRules(node) {
  if (node.type !== "Grid") return [];
  return node.columnOverrides.map(
    (override) => `@media(min-width:${override.minWidth}px){[data-prototype-node-id="${node.id}"]{grid-template-columns:repeat(${override.columns},minmax(0,1fr))}}`
  );
}
function collectNodeCss(node, output) {
  output.push(`[data-prototype-node-id="${node.id}"]{${layoutRules(node).join(";")}}`);
  output.push(...responsiveRules(node));
  output.push(...gridColumnRules(node));
  if (isStructuredPrototypeContainerNode(node)) {
    for (const child of node.children) collectNodeCss(child, output);
  }
}
function inputNodes(node, output) {
  if (node.type === "Input") output.push(node);
  if (isStructuredPrototypeContainerNode(node)) {
    for (const child of node.children) inputNodes(child, output);
  }
}
function formNodes(node, output) {
  if (node.type === "Form") output.push(node);
  if (isStructuredPrototypeContainerNode(node)) {
    for (const child of node.children) formNodes(child, output);
  }
}
function deriveFormInputBindings(document, requireComplete = true) {
  const forms = [];
  for (const page of document.pages) formNodes(page.root, forms);
  const result = [];
  for (const form of forms) {
    const definition = document.runtime.forms.find(
      (candidate) => candidate.id === form.formDefinitionId
    );
    if (definition === void 0) {
      throw new PrototypeRendererError(
        "renderer_form_definition_missing",
        `form node ${form.id} references an unknown runtime form`
      );
    }
    const inputs = [];
    for (const child of form.children) inputNodes(child, inputs);
    const boundFieldIds = /* @__PURE__ */ new Set();
    for (const input of inputs) {
      if (input.formDefinitionId === null && input.formFieldId === null) continue;
      if (input.formDefinitionId !== definition.id || input.formFieldId === null) {
        throw new PrototypeRendererError(
          "renderer_form_binding_invalid",
          `input node ${input.id} does not belong to runtime form ${definition.id}`
        );
      }
      const field = definition.fields.find((candidate) => candidate.id === input.formFieldId);
      if (field === void 0) {
        throw new PrototypeRendererError(
          "renderer_form_field_missing",
          `input node ${input.id} references an unknown runtime field`
        );
      }
      if (boundFieldIds.has(field.id)) {
        throw new PrototypeRendererError(
          "renderer_form_binding_duplicate",
          `runtime field ${field.id} is bound more than once in form node ${form.id}`
        );
      }
      const compatible = field.valueType === "integer" && input.inputType === "number" || field.valueType === "string" && input.inputType !== "number";
      if (!compatible) {
        throw new PrototypeRendererError(
          "renderer_form_binding_type_mismatch",
          `input node ${input.id} does not match runtime field ${field.id}`
        );
      }
      boundFieldIds.add(field.id);
      result.push({
        nodeId: input.id,
        formId: definition.id,
        fieldId: field.id,
        valueType: field.valueType
      });
    }
    if (requireComplete && boundFieldIds.size !== definition.fields.length) {
      throw new PrototypeRendererError(
        "renderer_form_binding_incomplete",
        `form node ${form.id} must bind every runtime field exactly once`
      );
    }
  }
  return result;
}
function renderNode(node, bindings) {
  const common = `data-prototype-node-id="${node.id}" data-prototype-node-type="${node.type}"`;
  switch (node.type) {
    case "Freeform":
      return `<div ${common} class="prototype-freeform">${node.children.map((child) => renderNode(child, bindings)).join("")}</div>`;
    case "Stack":
      return `<div ${common} class="prototype-stack">${node.children.map((child) => renderNode(child, bindings)).join("")}</div>`;
    case "Grid":
      return `<div ${common} class="prototype-grid">${node.children.map((child) => renderNode(child, bindings)).join("")}</div>`;
    case "Form":
      return `<form ${common} class="prototype-form" data-prototype-form-id="${node.formDefinitionId}" novalidate>${node.children.map((child) => renderNode(child, bindings)).join("")}</form>`;
    case "Text": {
      const tag = node.semantic === "heading" ? "h2" : node.semantic === "label" ? "strong" : "p";
      return `<${tag} ${common} class="prototype-text prototype-text-${node.semantic} prototype-tone-${node.tone}">${escapeHtml(node.content)}</${tag}>`;
    }
    case "Input": {
      const binding = bindings.get(node.id);
      const bindingAttributes = binding === void 0 ? "" : ` data-runtime-form-id="${binding.formId}" data-runtime-field-id="${binding.fieldId}" data-runtime-value-type="${binding.valueType}"`;
      return `<label ${common} class="prototype-input"><span>${escapeHtml(node.label)}</span><input type="${node.inputType}" value="${escapeHtml(node.value)}" placeholder="${escapeHtml(node.placeholder)}"${node.required ? " required" : ""}${node.disabled ? " disabled" : ""}${bindingAttributes}></label>`;
    }
    case "Button": {
      const trigger = node.disabled ? "" : ` data-runtime-node-id="${node.id}"`;
      return `<button ${common} type="button" class="prototype-button prototype-button-${node.variant} prototype-button-${node.size}"${node.disabled ? " disabled" : ""}${trigger}>${escapeHtml(node.label)}</button>`;
    }
    case "Divider":
      return `<div ${common} class="prototype-divider prototype-divider-${node.tone}" role="separator"></div>`;
    case "Badge":
      return `<span ${common} class="prototype-badge prototype-badge-${node.tone}">${escapeHtml(node.label)}</span>`;
    case "Table":
      return `<div ${common} class="prototype-table-wrap"><table class="prototype-table prototype-table-${node.density}"><thead><tr>${node.columns.map((column) => `<th data-column-key="${escapeHtml(column.key)}">${escapeHtml(column.label)}</th>`).join("")}</tr></thead><tbody>${node.rows.map((row) => `<tr data-static-row-id="${row.id}">${node.columns.map((column) => `<td>${escapeHtml(row.cells.find((cell) => cell.columnKey === column.key)?.value ?? "")}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  }
}
function shellRules(document) {
  const shell = document.settings.shell;
  if (shell.kind === "topbar") {
    return ".prototype-shell-topbar{display:flex;flex-direction:column}.prototype-shell-topbar>.prototype-header{display:flex;align-items:center;gap:20px;min-height:64px;padding:10px 24px}.prototype-shell-topbar .prototype-nav{display:flex;flex:1;flex-wrap:wrap;gap:4px}.prototype-shell-topbar .prototype-role{margin-left:auto}.prototype-shell-topbar .prototype-page{min-height:calc(100vh - 116px)}";
  }
  return `.prototype-shell-sidebar{display:flex;flex-direction:column}.prototype-shell-sidebar>.prototype-sidebar{display:flex;align-items:center;gap:20px;min-height:64px;padding:10px 16px}.prototype-shell-sidebar .prototype-nav{display:flex;flex:1;gap:4px;overflow:auto}.prototype-shell-sidebar .prototype-role{margin-left:auto}.prototype-shell-sidebar .prototype-page{min-height:calc(100vh - 116px)}@media(min-width:${shell.expandedMinWidth}px){.prototype-shell-sidebar{display:grid;grid-template-columns:${shell.navigationWidth}px minmax(0,1fr)}.prototype-shell-sidebar>.prototype-sidebar{min-height:100vh;display:flex;flex-direction:column;align-items:stretch;gap:0;padding:20px 14px}.prototype-shell-sidebar .prototype-nav{display:grid;flex:0 0 auto;margin-top:24px;overflow:visible}.prototype-shell-sidebar .prototype-nav button{width:100%;text-align:left}.prototype-shell-sidebar .prototype-role{display:grid;margin:auto 0 0}.prototype-shell-sidebar .prototype-page{min-height:calc(100vh - 52px)}}`;
}
function renderStyles(document) {
  const theme = resolvePrototypeShellTheme(document);
  const tokenRules = [
    `--prototype-accent:${theme.accent}`,
    `--prototype-accent-text:${theme.accentText}`,
    `--prototype-navigation-background:${theme.navigationBackground}`,
    `--prototype-navigation-text:${theme.navigationText}`,
    `--prototype-content-background:${theme.contentBackground}`,
    `--prototype-content-text:${theme.contentText}`,
    `--prototype-surface:${theme.surface}`,
    `--prototype-surface-text:${theme.surfaceText}`,
    "--prototype-text:var(--prototype-content-text)",
    ...document.tokens.colors.map(
      (token, index) => `--prototype-color-${index}:${safeTokenValue("color", token.value)}`
    ),
    ...document.tokens.spacing.map(
      (token, index) => `--prototype-space-${index}:${safeTokenValue("spacing", token.value)}`
    )
  ];
  const nodeRules = [
    ".prototype-divider{height:1px;background:#c9d2ce}",
    ".prototype-divider-muted{background:#e6eae8}",
    ".prototype-badge{display:inline-flex;width:fit-content;align-items:center;gap:4px;border:1px solid transparent;padding:2px 8px;font-size:11px;font-weight:700;line-height:1.5}",
    ".prototype-badge-default{background:#eef1ef;color:#39443f}",
    ".prototype-badge-success{background:#e9f4ec;color:#237a45}",
    ".prototype-badge-warning{background:#fff2d8;color:#936221}",
    ".prototype-badge-danger{background:#fff1f3;color:#8c1d31}"
  ];
  for (const page of document.pages) collectNodeCss(page.root, nodeRules);
  return `:root{${tokenRules.join(";")};color-scheme:${document.settings.theme === "system" ? "light dark" : document.settings.theme};font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}*{box-sizing:border-box}html,body{margin:0;min-height:100%;background:var(--prototype-content-background);color:var(--prototype-text)}button,input,select{font:inherit}.prototype-toolbar,.prototype-role select,.prototype-input input,.prototype-button-secondary,.prototype-table-wrap{--prototype-text:var(--prototype-surface-text);color:var(--prototype-surface-text)}.prototype-shell{min-height:100vh}.prototype-header,.prototype-sidebar{background:var(--prototype-navigation-background);color:var(--prototype-navigation-text)}.prototype-brand{font-size:18px;font-weight:800;white-space:nowrap}.prototype-nav button{border:0;background:transparent;color:inherit;opacity:.75;min-height:40px;padding:0 12px;cursor:pointer}.prototype-nav button[aria-current="page"]{background:var(--prototype-accent);color:var(--prototype-accent-text);opacity:1;font-weight:700}.prototype-role{display:flex;align-items:center;gap:8px;color:inherit;font-size:12px}.prototype-role[hidden]{display:none!important}.prototype-role select{min-height:34px;border:1px solid color-mix(in srgb,var(--prototype-navigation-text) 32%,transparent);background:var(--prototype-surface);color:var(--prototype-text);padding:0 8px}.prototype-main{min-width:0;flex:1;background:var(--prototype-content-background);color:var(--prototype-content-text)}.prototype-toolbar{min-height:52px;display:flex;align-items:center;gap:16px;border-bottom:1px solid color-mix(in srgb,var(--prototype-text) 14%,transparent);background:var(--prototype-surface);padding:8px 24px}.prototype-toolbar-title{font-size:14px;font-weight:700}.prototype-notification{display:none;margin:16px 24px 0;border:1px solid #b6d7cf;background:#e9f4ec;color:#237a45;padding:10px 12px;font-size:13px}.prototype-notification[data-visible="true"]{display:block}.prototype-notification[data-level="error"]{border-color:#e4a8b2;background:#fff1f3;color:#8c1d31}.prototype-page{display:none}.prototype-page[data-active="true"]{display:block}.prototype-freeform,.prototype-stack,.prototype-grid,.prototype-form{min-width:0}.prototype-text{margin:0;line-height:1.5}.prototype-text-heading{font-size:24px;font-weight:800}.prototype-text-caption{font-size:12px}.prototype-tone-muted{color:color-mix(in srgb,var(--prototype-text) 64%,transparent)}.prototype-tone-success{color:#237a45}.prototype-tone-warning{color:#936221}.prototype-tone-danger{color:#8c1d31}.prototype-input{display:grid;gap:6px;color:inherit;font-size:12px}.prototype-input input{min-height:42px;border:1px solid color-mix(in srgb,var(--prototype-text) 20%,transparent);background:var(--prototype-surface);padding:0 12px;color:var(--prototype-text)}.prototype-button{border:1px solid transparent;cursor:pointer;font-weight:700}.prototype-button-small{min-height:32px;padding:0 12px;font-size:12px}.prototype-button-medium{min-height:40px;padding:0 16px;font-size:13px}.prototype-button-large{min-height:48px;padding:0 20px;font-size:14px}.prototype-button-primary{background:var(--prototype-accent);color:var(--prototype-accent-text)}.prototype-button-secondary{border-color:color-mix(in srgb,var(--prototype-text) 20%,transparent);background:var(--prototype-surface);color:var(--prototype-text)}.prototype-button-danger{background:#8c1d31;color:#fff}.prototype-button-ghost{background:transparent;color:var(--prototype-accent)}.prototype-button:disabled{cursor:not-allowed;opacity:.45}.prototype-table-wrap{overflow:auto;border:1px solid color-mix(in srgb,var(--prototype-text) 15%,transparent);background:var(--prototype-surface)}.prototype-table{width:100%;border-collapse:collapse;font-size:13px}.prototype-table th,.prototype-table td{border-bottom:1px solid color-mix(in srgb,var(--prototype-text) 12%,transparent);text-align:left}.prototype-table-compact th,.prototype-table-compact td{padding:8px 10px}.prototype-table-comfortable th,.prototype-table-comfortable td{padding:12px 14px}.prototype-table th{background:color-mix(in srgb,var(--prototype-surface) 94%,var(--prototype-text));color:color-mix(in srgb,var(--prototype-text) 64%,transparent);font-size:11px;text-transform:uppercase}.prototype-table tbody tr[data-entity-id]{cursor:pointer}.prototype-table tbody tr[data-entity-id]:hover{background:color-mix(in srgb,var(--prototype-accent) 8%,transparent)}.prototype-runtime-error{position:fixed;right:16px;bottom:16px;max-width:420px;border:1px solid #e4a8b2;background:#fff1f3;color:#8c1d31;padding:12px;font-size:12px;z-index:20}${shellRules(document)}${nodeRules.join("")}@media(max-width:767px){.prototype-header{align-items:flex-start;flex-wrap:wrap;padding:12px}.prototype-header .prototype-nav{order:3;flex-basis:100%;flex-wrap:nowrap;overflow:auto}.prototype-nav button{white-space:nowrap}.prototype-toolbar{padding:8px 12px}.prototype-text-heading{font-size:20px}}`;
}
function renderRoleControl(document, showRoleControl) {
  return `<label class="prototype-role"${showRoleControl ? "" : " hidden"}><span data-current-role-label></span><select data-role-select aria-label="Simulated role">${document.runtime.roles.map((role) => `<option value="${role.id}">${escapeHtml(role.label)}</option>`).join("")}</select></label>`;
}
function renderNavigation(document) {
  return `<nav class="prototype-nav" aria-label="Prototype navigation">${document.navigation.items.map((item) => `<button type="button" data-navigation-target="${item.targetPageId}">${escapeHtml(item.label)}</button>`).join("")}</nav>`;
}
function renderHtml(document, documentHash) {
  const bindings = new Map(
    deriveFormInputBindings(document).map((binding) => [binding.nodeId, binding])
  );
  const showRoleControl = structuredPrototypeShowsRoleControl(document);
  const navigation = `${renderNavigation(document)}${renderRoleControl(document, showRoleControl)}`;
  const shellNavigation = document.settings.shell.kind === "sidebar" ? `<aside class="prototype-sidebar prototype-navigation"><div class="prototype-brand">${escapeHtml(document.settings.shell.title)}</div>${navigation}</aside>` : `<header class="prototype-header prototype-navigation"><div class="prototype-brand">${escapeHtml(document.settings.shell.title)}</div>${navigation}</header>`;
  const main2 = `<main class="prototype-main"><header class="prototype-toolbar"><div class="prototype-toolbar-title" data-current-page-title>${escapeHtml(document.pages[0]?.title ?? document.title)}</div></header><div class="prototype-notification" data-runtime-notification data-visible="false"></div>${document.pages.map((page) => `<section class="prototype-page" data-prototype-page-id="${page.id}" data-page-title="${escapeHtml(page.title)}" data-active="false">${renderNode(page.root, bindings)}</section>`).join("")}</main>`;
  return `<!doctype html><html lang="${document.locale}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="prototype-document-hash" content="${documentHash}"><meta http-equiv="Content-Security-Policy" content="default-src 'none';script-src 'self';style-src 'self';connect-src 'self';img-src 'self' data:;font-src 'self';base-uri 'none';form-action 'none';frame-ancestors 'self'"><title>${escapeHtml(document.title)}</title><link rel="stylesheet" href="./styles.css"></head><body><div class="prototype-shell prototype-shell-${document.settings.shell.kind}">${shellNavigation}${main2}</div><div class="prototype-runtime-error" data-runtime-error hidden></div><script src="./runtime.js" defer></script></body></html>`;
}
function countNodes(node) {
  if (!isStructuredPrototypeContainerNode(node)) return 1;
  return 1 + node.children.reduce((total, child) => total + countNodes(child), 0);
}
function renderPrototypeDocument(document, documentJson, documentHash, publicRuntimeSource) {
  if (document.assetRefs.length > 0) {
    throw new PrototypeRendererError(
      "renderer_assets_unsupported",
      "renderer asset resolution is unavailable for this compatibility version"
    );
  }
  const bindings = deriveFormInputBindings(document);
  const nodeCount = document.pages.reduce((total, page) => total + countNodes(page.root), 0);
  const preflight = {
    contractVersion: 1,
    checks: [
      { code: "document-schema", status: "passed", evidence: `schema:${document.schemaVersion}` },
      {
        code: "runtime-graph",
        status: "passed",
        evidence: `rules:${document.runtime.rules.length}`
      },
      { code: "node-bindings", status: "passed", evidence: `nodes:${nodeCount}` },
      {
        code: "sandbox-policy",
        status: "passed",
        evidence: PROTOTYPE_RENDERER_SANDBOX_POLICY_VERSION
      }
    ],
    pageCount: document.pages.length,
    nodeCount,
    formBindingCount: bindings.length,
    externalAssetCount: 0
  };
  const files = [
    { relativePath: "document.json", content: documentJson },
    { relativePath: "index.html", content: renderHtml(document, documentHash) },
    { relativePath: "runtime.js", content: publicRuntimeSource },
    { relativePath: "styles.css", content: renderStyles(document) }
  ];
  files.sort((left, right) => left.relativePath.localeCompare(right.relativePath, "en"));
  return { files, preflight };
}

// src/features/prototype/runtime/runtimeStateCodec.ts
var RuntimeStateCodecError = class extends Error {
  constructor(message) {
    super(message);
    this.name = "RuntimeStateCodecError";
  }
};
function isRecord(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function requireRecord(value, path) {
  if (!isRecord(value)) {
    throw new RuntimeStateCodecError(`${path} must be an object`);
  }
  return value;
}
function requireExactKeys(record3, expectedKeys, path) {
  const expected = new Set(expectedKeys);
  for (const key of Object.keys(record3)) {
    if (!expected.has(key)) {
      throw new RuntimeStateCodecError(`${path} contains unknown field ${key}`);
    }
  }
  for (const key of expectedKeys) {
    if (!Object.hasOwn(record3, key)) {
      throw new RuntimeStateCodecError(`${path} is missing field ${key}`);
    }
  }
}
function requireString(value, path) {
  if (typeof value !== "string") {
    throw new RuntimeStateCodecError(`${path} must be a string`);
  }
  return value;
}
function requireBoolean(value, path) {
  if (typeof value !== "boolean") {
    throw new RuntimeStateCodecError(`${path} must be a boolean`);
  }
  return value;
}
function requireSafeInteger(value, path) {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || Object.is(value, -0)) {
    throw new RuntimeStateCodecError(`${path} must be a safe integer`);
  }
  return value;
}
function requireArray(value, path) {
  if (!Array.isArray(value)) {
    throw new RuntimeStateCodecError(`${path} must be an array`);
  }
  return value;
}
function requireLiteral(value, allowed, path) {
  if (typeof value === "string") {
    for (const candidate of allowed) {
      if (candidate === value) {
        return candidate;
      }
    }
  }
  throw new RuntimeStateCodecError(`${path} has an unsupported value`);
}
function parseRuntimeValue(value, path) {
  const record3 = requireRecord(value, path);
  const type = requireLiteral(
    record3["type"],
    ["null", "boolean", "integer", "string", "enum", "entityRef"],
    `${path}.type`
  );
  switch (type) {
    case "null":
      requireExactKeys(record3, ["type"], path);
      return { type: "null" };
    case "boolean":
      requireExactKeys(record3, ["type", "value"], path);
      return { type: "boolean", value: requireBoolean(record3["value"], `${path}.value`) };
    case "integer":
      requireExactKeys(record3, ["type", "value"], path);
      return { type: "integer", value: requireSafeInteger(record3["value"], `${path}.value`) };
    case "string":
      requireExactKeys(record3, ["type", "value"], path);
      return { type: "string", value: requireString(record3["value"], `${path}.value`) };
    case "enum":
      requireExactKeys(record3, ["type", "value"], path);
      return { type: "enum", value: requireString(record3["value"], `${path}.value`) };
    case "entityRef":
      requireExactKeys(record3, ["type", "schemaId", "entityId"], path);
      return {
        type: "entityRef",
        schemaId: requireString(record3["schemaId"], `${path}.schemaId`),
        entityId: requireString(record3["entityId"], `${path}.entityId`)
      };
  }
}
function parseFieldValue(value, path) {
  const record3 = requireRecord(value, path);
  requireExactKeys(record3, ["fieldId", "value"], path);
  return {
    fieldId: requireString(record3["fieldId"], `${path}.fieldId`),
    value: parseRuntimeValue(record3["value"], `${path}.value`)
  };
}
function parseVariableValue(value, path) {
  const record3 = requireRecord(value, path);
  requireExactKeys(record3, ["variableId", "value"], path);
  return {
    variableId: requireString(record3["variableId"], `${path}.variableId`),
    value: parseRuntimeValue(record3["value"], `${path}.value`)
  };
}
function parseEntity(value, path) {
  const record3 = requireRecord(value, path);
  requireExactKeys(record3, ["id", "schemaId", "fields"], path);
  return {
    id: requireString(record3["id"], `${path}.id`),
    schemaId: requireString(record3["schemaId"], `${path}.schemaId`),
    fields: requireArray(record3["fields"], `${path}.fields`).map(
      (field, index) => parseFieldValue(field, `${path}.fields[${index}]`)
    )
  };
}
function parseEntitySet(value, path) {
  const record3 = requireRecord(value, path);
  requireExactKeys(record3, ["schemaId", "entities"], path);
  return {
    schemaId: requireString(record3["schemaId"], `${path}.schemaId`),
    entities: requireArray(record3["entities"], `${path}.entities`).map(
      (entity, index) => parseEntity(entity, `${path}.entities[${index}]`)
    )
  };
}

// src/features/prototype/runtime/types.ts
var RUNTIME_FLOW_LAYOUT_NODE_LIMIT = 300;
var RUNTIME_FLOW_COORDINATE_LIMIT = 32768;

// src/features/prototype/runtime/runtimeInputCodec.ts
var MAX_EXPRESSION_DEPTH = 32;
var RuntimeInputCodecError = class extends Error {
  constructor(message) {
    super(message);
    this.name = "RuntimeInputCodecError";
  }
};
function isRecord2(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function requireRecord2(value, path) {
  if (!isRecord2(value)) {
    throw new RuntimeInputCodecError(`${path} must be an object`);
  }
  return value;
}
function requireExactKeys2(record3, expectedKeys, path) {
  const expected = new Set(expectedKeys);
  for (const key of Object.keys(record3)) {
    if (!expected.has(key)) {
      throw new RuntimeInputCodecError(`${path} contains unknown field ${key}`);
    }
  }
  for (const key of expectedKeys) {
    if (!Object.hasOwn(record3, key)) {
      throw new RuntimeInputCodecError(`${path} is missing field ${key}`);
    }
  }
}
function requireString2(value, path) {
  if (typeof value !== "string") {
    throw new RuntimeInputCodecError(`${path} must be a string`);
  }
  return value;
}
function requireNonEmptyString(value, path) {
  const parsed = requireString2(value, path);
  if (parsed.length === 0) {
    throw new RuntimeInputCodecError(`${path} must not be empty`);
  }
  return parsed;
}
function requireBoolean2(value, path) {
  if (typeof value !== "boolean") {
    throw new RuntimeInputCodecError(`${path} must be a boolean`);
  }
  return value;
}
function requireSafeInteger2(value, path) {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || Object.is(value, -0)) {
    throw new RuntimeInputCodecError(`${path} must be a safe integer`);
  }
  return value;
}
function requireArray2(value, path) {
  if (!Array.isArray(value)) {
    throw new RuntimeInputCodecError(`${path} must be an array`);
  }
  return value;
}
function requireLiteral2(value, allowed, path) {
  if (typeof value === "string") {
    for (const candidate of allowed) {
      if (candidate === value) {
        return candidate;
      }
    }
  }
  throw new RuntimeInputCodecError(`${path} has an unsupported value`);
}
function requireNullableSafeInteger(value, path) {
  return value === null ? null : requireSafeInteger2(value, path);
}
function requireFlowLayoutCoordinate(value, path) {
  const parsed = requireSafeInteger2(value, path);
  if (parsed < -RUNTIME_FLOW_COORDINATE_LIMIT || parsed > RUNTIME_FLOW_COORDINATE_LIMIT) {
    throw new RuntimeInputCodecError(
      `${path} must be between ${-RUNTIME_FLOW_COORDINATE_LIMIT} and ${RUNTIME_FLOW_COORDINATE_LIMIT}`
    );
  }
  return parsed;
}
function requireDepth(depth, path) {
  if (depth > MAX_EXPRESSION_DEPTH) {
    throw new RuntimeInputCodecError(`${path} exceeds the maximum expression depth`);
  }
}
function parseRole(value, path) {
  const record3 = requireRecord2(value, path);
  requireExactKeys2(record3, ["id", "key", "label"], path);
  return {
    id: requireNonEmptyString(record3["id"], `${path}.id`),
    key: requireNonEmptyString(record3["key"], `${path}.key`),
    label: requireString2(record3["label"], `${path}.label`)
  };
}
function parseVariable(value, path) {
  const record3 = requireRecord2(value, path);
  requireExactKeys2(
    record3,
    ["id", "key", "valueType", "nullable", "entitySchemaId", "defaultValue"],
    path
  );
  return {
    id: requireNonEmptyString(record3["id"], `${path}.id`),
    key: requireNonEmptyString(record3["key"], `${path}.key`),
    valueType: requireLiteral2(
      record3["valueType"],
      ["null", "boolean", "integer", "string", "enum", "entityRef"],
      `${path}.valueType`
    ),
    nullable: requireBoolean2(record3["nullable"], `${path}.nullable`),
    entitySchemaId: record3["entitySchemaId"] === null ? null : requireNonEmptyString(record3["entitySchemaId"], `${path}.entitySchemaId`),
    defaultValue: parseRuntimeValue(record3["defaultValue"], `${path}.defaultValue`)
  };
}
function parseEntityField(value, path) {
  const record3 = requireRecord2(value, path);
  requireExactKeys2(record3, ["id", "key", "valueType", "nullable"], path);
  return {
    id: requireNonEmptyString(record3["id"], `${path}.id`),
    key: requireNonEmptyString(record3["key"], `${path}.key`),
    valueType: requireLiteral2(
      record3["valueType"],
      ["null", "boolean", "integer", "string", "enum", "entityRef"],
      `${path}.valueType`
    ),
    nullable: requireBoolean2(record3["nullable"], `${path}.nullable`)
  };
}
function parseEntitySchema(value, path) {
  const record3 = requireRecord2(value, path);
  requireExactKeys2(record3, ["id", "key", "fields"], path);
  return {
    id: requireNonEmptyString(record3["id"], `${path}.id`),
    key: requireNonEmptyString(record3["key"], `${path}.key`),
    fields: requireArray2(record3["fields"], `${path}.fields`).map(
      (field, index) => parseEntityField(field, `${path}.fields[${index}]`)
    )
  };
}
function parseFormField(value, path) {
  const record3 = requireRecord2(value, path);
  requireExactKeys2(
    record3,
    ["id", "key", "valueType", "initialValue", "required", "minInteger"],
    path
  );
  const valueType = requireLiteral2(
    record3["valueType"],
    ["string", "integer"],
    `${path}.valueType`
  );
  const initialValue = parseRuntimeValue(record3["initialValue"], `${path}.initialValue`);
  let typedInitialValue;
  if (valueType === "string") {
    if (initialValue.type !== "string") {
      throw new RuntimeInputCodecError(`${path}.initialValue must be a string runtime value`);
    }
    typedInitialValue = initialValue;
  } else {
    if (initialValue.type !== "integer") {
      throw new RuntimeInputCodecError(`${path}.initialValue must be an integer runtime value`);
    }
    typedInitialValue = initialValue;
  }
  return {
    id: requireNonEmptyString(record3["id"], `${path}.id`),
    key: requireNonEmptyString(record3["key"], `${path}.key`),
    valueType,
    initialValue: typedInitialValue,
    required: requireBoolean2(record3["required"], `${path}.required`),
    minInteger: requireNullableSafeInteger(record3["minInteger"], `${path}.minInteger`)
  };
}
function parseForm(value, path) {
  const record3 = requireRecord2(value, path);
  requireExactKeys2(record3, ["id", "key", "fields"], path);
  return {
    id: requireNonEmptyString(record3["id"], `${path}.id`),
    key: requireNonEmptyString(record3["key"], `${path}.key`),
    fields: requireArray2(record3["fields"], `${path}.fields`).map(
      (field, index) => parseFormField(field, `${path}.fields[${index}]`)
    )
  };
}
function parseEntityRefExpression(value, path) {
  const record3 = requireRecord2(value, path);
  const kind = requireLiteral2(
    record3["kind"],
    ["variable", "eventEntityRef"],
    `${path}.kind`
  );
  if (kind === "variable") {
    requireExactKeys2(record3, ["kind", "variableId"], path);
    const expression2 = {
      kind,
      variableId: requireNonEmptyString(record3["variableId"], `${path}.variableId`)
    };
    return expression2;
  }
  requireExactKeys2(record3, ["kind"], path);
  const expression = { kind };
  return expression;
}
function parseValueExpression(value, path, depth = 0) {
  requireDepth(depth, path);
  const record3 = requireRecord2(value, path);
  const kind = requireLiteral2(
    record3["kind"],
    ["literal", "variable", "formField", "eventEntityRef", "entityField"],
    `${path}.kind`
  );
  switch (kind) {
    case "literal":
      requireExactKeys2(record3, ["kind", "value"], path);
      return { kind, value: parseRuntimeValue(record3["value"], `${path}.value`) };
    case "variable":
      requireExactKeys2(record3, ["kind", "variableId"], path);
      return {
        kind,
        variableId: requireNonEmptyString(record3["variableId"], `${path}.variableId`)
      };
    case "formField":
      requireExactKeys2(record3, ["kind", "formId", "fieldId"], path);
      return {
        kind,
        formId: requireNonEmptyString(record3["formId"], `${path}.formId`),
        fieldId: requireNonEmptyString(record3["fieldId"], `${path}.fieldId`)
      };
    case "eventEntityRef":
      requireExactKeys2(record3, ["kind"], path);
      return { kind };
    case "entityField": {
      requireExactKeys2(record3, ["kind", "entityRef", "fieldId", "fallback"], path);
      const expression = {
        kind,
        entityRef: parseEntityRefExpression(record3["entityRef"], `${path}.entityRef`),
        fieldId: requireNonEmptyString(record3["fieldId"], `${path}.fieldId`),
        fallback: parseRuntimeValue(record3["fallback"], `${path}.fallback`)
      };
      return expression;
    }
  }
}
function parsePredicate(value, path, depth = 0) {
  requireDepth(depth, path);
  const record3 = requireRecord2(value, path);
  const kind = requireLiteral2(
    record3["kind"],
    ["all", "roleIs", "formValid", "compare"],
    `${path}.kind`
  );
  switch (kind) {
    case "all":
      requireExactKeys2(record3, ["kind", "items"], path);
      return {
        kind,
        items: requireArray2(record3["items"], `${path}.items`).map(
          (item, index) => parsePredicate(item, `${path}.items[${index}]`, depth + 1)
        )
      };
    case "roleIs":
      requireExactKeys2(record3, ["kind", "roleId"], path);
      return {
        kind,
        roleId: requireNonEmptyString(record3["roleId"], `${path}.roleId`)
      };
    case "formValid":
      requireExactKeys2(record3, ["kind", "formId"], path);
      return {
        kind,
        formId: requireNonEmptyString(record3["formId"], `${path}.formId`)
      };
    case "compare":
      requireExactKeys2(record3, ["kind", "operator", "left", "right"], path);
      return {
        kind,
        operator: requireLiteral2(record3["operator"], ["eq", "ne"], `${path}.operator`),
        left: parseValueExpression(record3["left"], `${path}.left`, depth + 1),
        right: parseValueExpression(record3["right"], `${path}.right`, depth + 1)
      };
  }
}
function parseFieldAssignment(value, path) {
  const record3 = requireRecord2(value, path);
  requireExactKeys2(record3, ["fieldId", "value"], path);
  return {
    fieldId: requireNonEmptyString(record3["fieldId"], `${path}.fieldId`),
    value: parseValueExpression(record3["value"], `${path}.value`)
  };
}
function parseEffect(value, path) {
  const record3 = requireRecord2(value, path);
  const kind = requireLiteral2(
    record3["kind"],
    ["setVariable", "validateForm", "createEntity", "updateEntity", "navigate", "notify"],
    `${path}.kind`
  );
  switch (kind) {
    case "setVariable":
      requireExactKeys2(record3, ["kind", "variableId", "value"], path);
      return {
        kind,
        variableId: requireNonEmptyString(record3["variableId"], `${path}.variableId`),
        value: parseValueExpression(record3["value"], `${path}.value`)
      };
    case "validateForm":
      requireExactKeys2(record3, ["kind", "formId"], path);
      return {
        kind,
        formId: requireNonEmptyString(record3["formId"], `${path}.formId`)
      };
    case "createEntity":
      requireExactKeys2(record3, ["kind", "schemaId", "resultVariableId", "values"], path);
      return {
        kind,
        schemaId: requireNonEmptyString(record3["schemaId"], `${path}.schemaId`),
        resultVariableId: requireNonEmptyString(
          record3["resultVariableId"],
          `${path}.resultVariableId`
        ),
        values: requireArray2(record3["values"], `${path}.values`).map(
          (entry, index) => parseFieldAssignment(entry, `${path}.values[${index}]`)
        )
      };
    case "updateEntity":
      requireExactKeys2(record3, ["kind", "schemaId", "entityRef", "updates"], path);
      return {
        kind,
        schemaId: requireNonEmptyString(record3["schemaId"], `${path}.schemaId`),
        entityRef: parseEntityRefExpression(record3["entityRef"], `${path}.entityRef`),
        updates: requireArray2(record3["updates"], `${path}.updates`).map(
          (entry, index) => parseFieldAssignment(entry, `${path}.updates[${index}]`)
        )
      };
    case "navigate":
      requireExactKeys2(record3, ["kind", "targetPageId"], path);
      return {
        kind,
        targetPageId: requireNonEmptyString(record3["targetPageId"], `${path}.targetPageId`)
      };
    case "notify":
      requireExactKeys2(record3, ["kind", "level", "message"], path);
      return {
        kind,
        level: requireLiteral2(
          record3["level"],
          ["info", "success", "warning", "error"],
          `${path}.level`
        ),
        message: requireString2(record3["message"], `${path}.message`)
      };
  }
}
function parseRule(value, path) {
  const record3 = requireRecord2(value, path);
  requireExactKeys2(
    record3,
    ["id", "key", "enabled", "trigger", "guard", "effects", "guardFalseEffects"],
    path
  );
  const trigger = requireRecord2(record3["trigger"], `${path}.trigger`);
  requireExactKeys2(trigger, ["kind", "nodeId", "event"], `${path}.trigger`);
  if (trigger["kind"] !== "nodeEvent") {
    throw new RuntimeInputCodecError(`${path}.trigger.kind must equal nodeEvent`);
  }
  return {
    id: requireNonEmptyString(record3["id"], `${path}.id`),
    key: requireNonEmptyString(record3["key"], `${path}.key`),
    enabled: requireBoolean2(record3["enabled"], `${path}.enabled`),
    trigger: {
      kind: "nodeEvent",
      nodeId: requireNonEmptyString(trigger["nodeId"], `${path}.trigger.nodeId`),
      event: requireLiteral2(
        trigger["event"],
        ["click", "submit", "rowActivated"],
        `${path}.trigger.event`
      )
    },
    guard: record3["guard"] === null ? null : parsePredicate(record3["guard"], `${path}.guard`),
    effects: requireArray2(record3["effects"], `${path}.effects`).map(
      (effect, index) => parseEffect(effect, `${path}.effects[${index}]`)
    ),
    guardFalseEffects: requireArray2(record3["guardFalseEffects"], `${path}.guardFalseEffects`).map(
      (effect, index) => parseEffect(effect, `${path}.guardFalseEffects[${index}]`)
    )
  };
}
function parseViewBinding(value, path) {
  const record3 = requireRecord2(value, path);
  const target = requireLiteral2(
    record3["target"],
    ["textContent", "visibility", "tableRows"],
    `${path}.target`
  );
  if (target === "textContent") {
    requireExactKeys2(record3, ["id", "nodeId", "target", "value"], path);
    return {
      id: requireNonEmptyString(record3["id"], `${path}.id`),
      nodeId: requireNonEmptyString(record3["nodeId"], `${path}.nodeId`),
      target,
      value: parseValueExpression(record3["value"], `${path}.value`)
    };
  }
  if (target === "visibility") {
    requireExactKeys2(record3, ["id", "nodeId", "target", "predicate"], path);
    return {
      id: requireNonEmptyString(record3["id"], `${path}.id`),
      nodeId: requireNonEmptyString(record3["nodeId"], `${path}.nodeId`),
      target,
      predicate: parsePredicate(record3["predicate"], `${path}.predicate`)
    };
  }
  requireExactKeys2(
    record3,
    ["id", "nodeId", "target", "schemaId", "sortFieldId", "sortDirection"],
    path
  );
  return {
    id: requireNonEmptyString(record3["id"], `${path}.id`),
    nodeId: requireNonEmptyString(record3["nodeId"], `${path}.nodeId`),
    target,
    schemaId: requireNonEmptyString(record3["schemaId"], `${path}.schemaId`),
    sortFieldId: record3["sortFieldId"] === null ? null : requireNonEmptyString(record3["sortFieldId"], `${path}.sortFieldId`),
    sortDirection: requireLiteral2(
      record3["sortDirection"],
      ["asc", "desc"],
      `${path}.sortDirection`
    )
  };
}
function parseScenario(value, path) {
  const record3 = requireRecord2(value, path);
  requireExactKeys2(
    record3,
    [
      "id",
      "key",
      "actorRoleId",
      "startPageId",
      "initialVariables",
      "entityFixtures",
      "allowSimulatedRoleSwitch"
    ],
    path
  );
  return {
    id: requireNonEmptyString(record3["id"], `${path}.id`),
    key: requireNonEmptyString(record3["key"], `${path}.key`),
    actorRoleId: requireNonEmptyString(record3["actorRoleId"], `${path}.actorRoleId`),
    startPageId: requireNonEmptyString(record3["startPageId"], `${path}.startPageId`),
    initialVariables: requireArray2(record3["initialVariables"], `${path}.initialVariables`).map(
      (entry, index) => parseVariableValue(entry, `${path}.initialVariables[${index}]`)
    ),
    entityFixtures: requireArray2(record3["entityFixtures"], `${path}.entityFixtures`).map(
      (entry, index) => parseEntitySet(entry, `${path}.entityFixtures[${index}]`)
    ),
    allowSimulatedRoleSwitch: requireBoolean2(
      record3["allowSimulatedRoleSwitch"],
      `${path}.allowSimulatedRoleSwitch`
    )
  };
}
function parseFlowLayout(value, path) {
  const record3 = requireRecord2(value, path);
  requireExactKeys2(record3, ["nodes"], path);
  const rawNodes = requireArray2(record3["nodes"], `${path}.nodes`);
  if (rawNodes.length > RUNTIME_FLOW_LAYOUT_NODE_LIMIT) {
    throw new RuntimeInputCodecError(
      `${path}.nodes exceeds the maximum length of ${RUNTIME_FLOW_LAYOUT_NODE_LIMIT}`
    );
  }
  const nodes = rawNodes.map((value2, index) => {
    const nodePath = `${path}.nodes[${index}]`;
    const node = requireRecord2(value2, nodePath);
    requireExactKeys2(node, ["nodeId", "x", "y"], nodePath);
    return {
      nodeId: requireNonEmptyString(node["nodeId"], `${nodePath}.nodeId`),
      x: requireFlowLayoutCoordinate(node["x"], `${nodePath}.x`),
      y: requireFlowLayoutCoordinate(node["y"], `${nodePath}.y`)
    };
  });
  const seenNodeIds = /* @__PURE__ */ new Set();
  for (const node of nodes) {
    if (seenNodeIds.has(node.nodeId)) {
      throw new RuntimeInputCodecError(`${path}.nodes contains duplicate nodeId ${node.nodeId}`);
    }
    seenNodeIds.add(node.nodeId);
  }
  for (let index = 1; index < nodes.length; index += 1) {
    const previous = nodes[index - 1];
    const current = nodes[index];
    if (previous !== void 0 && current !== void 0 && current.nodeId < previous.nodeId) {
      throw new RuntimeInputCodecError(`${path}.nodes must use canonical nodeId order`);
    }
  }
  return { nodes };
}
function parseRuntimeDefinition(value) {
  const record3 = requireRecord2(value, "runtimeDefinition");
  const hasFlowLayout = Object.hasOwn(record3, "flowLayout");
  requireExactKeys2(
    record3,
    [
      "runtimeSchemaVersion",
      "pageIds",
      "roles",
      "variables",
      "entitySchemas",
      "forms",
      "viewBindings",
      "rules",
      "scenarios",
      ...hasFlowLayout ? ["flowLayout"] : []
    ],
    "runtimeDefinition"
  );
  if (record3["runtimeSchemaVersion"] !== 1) {
    throw new RuntimeInputCodecError("runtimeDefinition.runtimeSchemaVersion must equal 1");
  }
  return {
    runtimeSchemaVersion: 1,
    pageIds: requireArray2(record3["pageIds"], "runtimeDefinition.pageIds").map(
      (pageId, index) => requireNonEmptyString(pageId, `runtimeDefinition.pageIds[${index}]`)
    ),
    roles: requireArray2(record3["roles"], "runtimeDefinition.roles").map(
      (role, index) => parseRole(role, `runtimeDefinition.roles[${index}]`)
    ),
    variables: requireArray2(record3["variables"], "runtimeDefinition.variables").map(
      (variable, index) => parseVariable(variable, `runtimeDefinition.variables[${index}]`)
    ),
    entitySchemas: requireArray2(record3["entitySchemas"], "runtimeDefinition.entitySchemas").map(
      (schema, index) => parseEntitySchema(schema, `runtimeDefinition.entitySchemas[${index}]`)
    ),
    forms: requireArray2(record3["forms"], "runtimeDefinition.forms").map(
      (form, index) => parseForm(form, `runtimeDefinition.forms[${index}]`)
    ),
    viewBindings: requireArray2(record3["viewBindings"], "runtimeDefinition.viewBindings").map(
      (binding, index) => parseViewBinding(binding, `runtimeDefinition.viewBindings[${index}]`)
    ),
    rules: requireArray2(record3["rules"], "runtimeDefinition.rules").map(
      (rule, index) => parseRule(rule, `runtimeDefinition.rules[${index}]`)
    ),
    scenarios: requireArray2(record3["scenarios"], "runtimeDefinition.scenarios").map(
      (scenario, index) => parseScenario(scenario, `runtimeDefinition.scenarios[${index}]`)
    ),
    ...hasFlowLayout ? { flowLayout: parseFlowLayout(record3["flowLayout"], "runtimeDefinition.flowLayout") } : {}
  };
}

// src/features/prototype/structured/rendererDocumentCodec.ts
var RendererDocumentCodecError = class extends Error {
  constructor(message) {
    super(message);
    this.name = "RendererDocumentCodecError";
  }
};
function isRecord3(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function record(value, path) {
  if (!isRecord3(value)) throw new RendererDocumentCodecError(`${path} must be an object`);
  return value;
}
function exactKeys(value, keys, path, optionalKeys = []) {
  const expected = /* @__PURE__ */ new Set([...keys, ...optionalKeys]);
  for (const key of Object.keys(value)) {
    if (!expected.has(key)) {
      throw new RendererDocumentCodecError(`${path} contains unknown field ${key}`);
    }
  }
  for (const key of keys) {
    if (!Object.hasOwn(value, key)) {
      throw new RendererDocumentCodecError(`${path} is missing field ${key}`);
    }
  }
}
function canonicalNonNegativeDecimal(value, path) {
  const parsed = string(value, path);
  if (!/^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,4})?$/u.test(parsed)) {
    throw new RendererDocumentCodecError(`${path} must be a canonical non-negative decimal`);
  }
  const numeric = Number(parsed);
  if (numeric > 4096) {
    throw new RendererDocumentCodecError(`${path} must not exceed 4096`);
  }
  return numeric;
}
function canonicalPositiveDecimal(value, path) {
  const numeric = canonicalNonNegativeDecimal(value, path);
  if (numeric <= 0) {
    throw new RendererDocumentCodecError(`${path} must be positive`);
  }
  return numeric;
}
function string(value, path) {
  if (typeof value !== "string") throw new RendererDocumentCodecError(`${path} must be a string`);
  return value;
}
function nonEmptyString(value, path) {
  const parsed = string(value, path);
  if (parsed.length === 0) throw new RendererDocumentCodecError(`${path} must not be empty`);
  return parsed;
}
function boundedNonEmptyString(value, maximumLength, path) {
  const parsed = nonEmptyString(value, path);
  if (parsed.length > maximumLength) {
    throw new RendererDocumentCodecError(
      `${path} must contain at most ${maximumLength} characters`
    );
  }
  return parsed;
}
function boolean(value, path) {
  if (typeof value !== "boolean") {
    throw new RendererDocumentCodecError(`${path} must be a boolean`);
  }
  return value;
}
function integer(value, path) {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || Object.is(value, -0)) {
    throw new RendererDocumentCodecError(`${path} must be a safe integer`);
  }
  return value;
}
function boundedInteger(value, minimum, maximum, path) {
  const parsed = integer(value, path);
  if (parsed < minimum || parsed > maximum) {
    throw new RendererDocumentCodecError(`${path} must be between ${minimum} and ${maximum}`);
  }
  return parsed;
}
function array(value, path) {
  if (!Array.isArray(value)) throw new RendererDocumentCodecError(`${path} must be an array`);
  return value;
}
function boundedArray(value, minimumLength, maximumLength, path) {
  const parsed = array(value, path);
  if (parsed.length < minimumLength || parsed.length > maximumLength) {
    throw new RendererDocumentCodecError(
      `${path} must contain between ${minimumLength} and ${maximumLength} items`
    );
  }
  return parsed;
}
function literal(value, values, path) {
  if (typeof value === "string" && values.includes(value)) return value;
  throw new RendererDocumentCodecError(`${path} has an unsupported value`);
}
function uuid(value, path) {
  const parsed = string(value, path);
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u.test(parsed)) {
    throw new RendererDocumentCodecError(`${path} must be a canonical UUID`);
  }
  return parsed;
}
function registerEntityId(value, path, entityIds) {
  const id = uuid(value, path);
  if (entityIds.has(id)) throw new RendererDocumentCodecError(`${path} is duplicated`);
  entityIds.add(id);
  return id;
}
function technicalKey(value, path) {
  const parsed = string(value, path);
  if (!/^[a-z][a-z0-9-]{0,63}$/u.test(parsed)) {
    throw new RendererDocumentCodecError(`${path} must be a technical key`);
  }
  return parsed;
}
function validateLength(value, path) {
  const item = record(value, path);
  exactKeys(item, ["unit", "value"], path);
  const unit = literal(item["unit"], ["px", "percent", "rem", "auto"], `${path}.unit`);
  if (unit === "auto") {
    if (item["value"] !== null) {
      throw new RendererDocumentCodecError(`${path}.value must be null for auto length`);
    }
    return;
  }
  const parsed = string(item["value"], `${path}.value`);
  if (!/^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,4})?$/u.test(parsed)) {
    throw new RendererDocumentCodecError(`${path}.value must be a canonical decimal`);
  }
  const numeric = Number(parsed);
  if (unit === "percent" && numeric > 100) {
    throw new RendererDocumentCodecError(`${path}.value must not exceed 100 for percent length`);
  }
  if (unit === "px" && numeric > 4096) {
    throw new RendererDocumentCodecError(`${path}.value must not exceed 4096 for px length`);
  }
  if (unit === "rem" && numeric > 256) {
    throw new RendererDocumentCodecError(`${path}.value must not exceed 256 for rem length`);
  }
}
function validatePosition(value, path) {
  const item = record(value, path);
  exactKeys(item, ["x", "y"], path);
  for (const axis of ["x", "y"]) {
    canonicalNonNegativeDecimal(item[axis], `${path}.${axis}`);
  }
}
function validateFreeformGrids(value, path, width, height, entityIds, colorTokenKeys) {
  const grids = value === void 0 ? [] : boundedArray(value, 0, 8, path);
  grids.forEach((grid, index) => {
    const gridPath = `${path}[${index}]`;
    const item = record(grid, gridPath);
    exactKeys(
      item,
      ["id", "version", "type", "visible", "snapEnabled", "origin", "params"],
      gridPath
    );
    registerEntityId(item["id"], `${gridPath}.id`, entityIds);
    if (item["version"] !== 1) {
      throw new RendererDocumentCodecError(`${gridPath}.version must equal 1`);
    }
    const type = literal(item["type"], ["square", "columns", "rows"], `${gridPath}.type`);
    boolean(item["visible"], `${gridPath}.visible`);
    boolean(item["snapEnabled"], `${gridPath}.snapEnabled`);
    validatePosition(item["origin"], `${gridPath}.origin`);
    const origin = record(item["origin"], `${gridPath}.origin`);
    const originX = Number(origin["x"]);
    const originY = Number(origin["y"]);
    if (originX >= width || originY >= height) {
      throw new RendererDocumentCodecError(`${gridPath}.origin must remain inside its Freeform`);
    }
    const params = record(item["params"], `${gridPath}.params`);
    const validatePresentation = () => {
      const colorTokenKey = technicalKey(
        params["colorTokenKey"],
        `${gridPath}.params.colorTokenKey`
      );
      if (!colorTokenKeys.has(colorTokenKey)) {
        throw new RendererDocumentCodecError(
          `${gridPath}.params.colorTokenKey references an unknown color token`
        );
      }
      const opacity = canonicalNonNegativeDecimal(params["opacity"], `${gridPath}.params.opacity`);
      if (opacity > 1) {
        throw new RendererDocumentCodecError(`${gridPath}.params.opacity must be between 0 and 1`);
      }
    };
    if (type === "square") {
      exactKeys(params, ["size", "colorTokenKey", "opacity"], `${gridPath}.params`);
      const size = canonicalPositiveDecimal(params["size"], `${gridPath}.params.size`);
      if (originX + size > width || originY + size > height) {
        throw new RendererDocumentCodecError(`${gridPath} does not fit inside its Freeform`);
      }
      validatePresentation();
      return;
    }
    exactKeys(
      params,
      ["count", "itemSize", "gutter", "margin", "alignment", "colorTokenKey", "opacity"],
      `${gridPath}.params`
    );
    const count = boundedInteger(params["count"], 1, 24, `${gridPath}.params.count`);
    const gutter = canonicalNonNegativeDecimal(params["gutter"], `${gridPath}.params.gutter`);
    const margin = canonicalNonNegativeDecimal(params["margin"], `${gridPath}.params.margin`);
    const alignment = literal(
      params["alignment"],
      ["stretch", "start", "center", "end"],
      `${gridPath}.params.alignment`
    );
    const itemSize = params["itemSize"] === null ? null : canonicalPositiveDecimal(params["itemSize"], `${gridPath}.params.itemSize`);
    if (alignment === "stretch" !== (itemSize === null)) {
      throw new RendererDocumentCodecError(
        `${gridPath}.params.itemSize must be null only for stretch alignment`
      );
    }
    const axisLength = type === "columns" ? width - originX : height - originY;
    const occupiedWithoutItems = margin * 2 + gutter * (count - 1);
    const available = axisLength - occupiedWithoutItems;
    if (available <= 0 || itemSize !== null && itemSize * count > available) {
      throw new RendererDocumentCodecError(`${gridPath} does not fit inside its Freeform`);
    }
    validatePresentation();
  });
}
function validateLayoutUpdate(value, path, allowPosition = false) {
  const item = record(value, path);
  const allowed = /* @__PURE__ */ new Set([
    "width",
    "minWidth",
    "maxWidth",
    "height",
    "minHeight",
    "maxHeight",
    "grow",
    "shrink",
    "alignSelf",
    ...allowPosition ? ["position"] : []
  ]);
  for (const key of Object.keys(item)) {
    if (!allowed.has(key)) {
      throw new RendererDocumentCodecError(`${path} contains unknown field ${key}`);
    }
  }
  if (Object.keys(item).length === 0) {
    throw new RendererDocumentCodecError(`${path} must contain an update`);
  }
  for (const key of ["width", "height"]) {
    if (Object.hasOwn(item, key)) validateLength(item[key], `${path}.${key}`);
  }
  for (const key of ["minWidth", "maxWidth", "minHeight", "maxHeight"]) {
    if (Object.hasOwn(item, key) && item[key] !== null) validateLength(item[key], `${path}.${key}`);
  }
  for (const key of ["grow", "shrink"]) {
    if (Object.hasOwn(item, key)) boundedInteger(item[key], 0, 12, `${path}.${key}`);
  }
  if (Object.hasOwn(item, "alignSelf")) {
    literal(
      item["alignSelf"],
      ["auto", "start", "center", "end", "stretch"],
      `${path}.alignSelf`
    );
  }
  if (Object.hasOwn(item, "position")) {
    if (item["position"] !== null) validatePosition(item["position"], `${path}.position`);
  }
}
function validateLayout(value, path) {
  const item = record(value, path);
  const required = [
    "width",
    "minWidth",
    "maxWidth",
    "height",
    "minHeight",
    "maxHeight",
    "grow",
    "shrink",
    "alignSelf"
  ];
  const allowed = [...required, "position"];
  for (const key of Object.keys(item)) {
    if (!allowed.includes(key)) {
      throw new RendererDocumentCodecError(`${path} contains unknown field ${key}`);
    }
  }
  for (const key of required) {
    if (!Object.hasOwn(item, key)) {
      throw new RendererDocumentCodecError(`${path} is missing field ${key}`);
    }
  }
  validateLength(item["width"], `${path}.width`);
  validateLength(item["height"], `${path}.height`);
  for (const key of ["minWidth", "maxWidth", "minHeight", "maxHeight"]) {
    if (item[key] !== null) validateLength(item[key], `${path}.${key}`);
  }
  boundedInteger(item["grow"], 0, 12, `${path}.grow`);
  boundedInteger(item["shrink"], 0, 12, `${path}.shrink`);
  literal(
    item["alignSelf"],
    ["auto", "start", "center", "end", "stretch"],
    `${path}.alignSelf`
  );
  if (Object.hasOwn(item, "position")) validatePosition(item["position"], `${path}.position`);
}
function validatePadding(value, path) {
  const item = record(value, path);
  exactKeys(item, ["top", "right", "bottom", "left"], path);
  for (const key of ["top", "right", "bottom", "left"])
    boundedInteger(item[key], 0, 256, `${path}.${key}`);
}
function validateCommon(item, path) {
  uuid(item["id"], `${path}.id`);
  boundedNonEmptyString(item["name"], 80, `${path}.name`);
  literal(item["visibility"], ["visible", "hidden"], `${path}.visibility`);
  validateLayout(item["layoutItem"], `${path}.layoutItem`);
  const breakpoints = /* @__PURE__ */ new Set();
  const breakpointOrder = { sm: 0, md: 1, lg: 2 };
  let previousBreakpointOrder = -1;
  boundedArray(item["responsive"], 0, 3, `${path}.responsive`).forEach((override, index) => {
    const responsive = record(override, `${path}.responsive[${index}]`);
    exactKeys(responsive, ["breakpoint", "layoutItem"], `${path}.responsive[${index}]`);
    const breakpoint = literal(
      responsive["breakpoint"],
      ["sm", "md", "lg"],
      `${path}.responsive[${index}].breakpoint`
    );
    if (breakpoints.has(breakpoint)) {
      throw new RendererDocumentCodecError(`${path}.responsive contains duplicate breakpoint`);
    }
    if (breakpointOrder[breakpoint] <= previousBreakpointOrder) {
      throw new RendererDocumentCodecError(
        `${path}.responsive must use strictly increasing breakpoint order`
      );
    }
    breakpoints.add(breakpoint);
    previousBreakpointOrder = breakpointOrder[breakpoint];
    validateLayoutUpdate(responsive["layoutItem"], `${path}.responsive[${index}].layoutItem`);
  });
}
function validateTable(value, path, entityIds) {
  array(value["columns"], `${path}.columns`).forEach((column, index) => {
    const item = record(column, `${path}.columns[${index}]`);
    exactKeys(item, ["key", "label", "fieldId"], `${path}.columns[${index}]`);
    technicalKey(item["key"], `${path}.columns[${index}].key`);
    nonEmptyString(item["label"], `${path}.columns[${index}].label`);
    if (item["fieldId"] !== null) uuid(item["fieldId"], `${path}.columns[${index}].fieldId`);
  });
  array(value["rows"], `${path}.rows`).forEach((row, rowIndex) => {
    const item = record(row, `${path}.rows[${rowIndex}]`);
    exactKeys(item, ["id", "cells"], `${path}.rows[${rowIndex}]`);
    registerEntityId(item["id"], `${path}.rows[${rowIndex}].id`, entityIds);
    array(item["cells"], `${path}.rows[${rowIndex}].cells`).forEach((cell, cellIndex) => {
      const parsed = record(cell, `${path}.rows[${rowIndex}].cells[${cellIndex}]`);
      exactKeys(parsed, ["columnKey", "value"], `${path}.rows[${rowIndex}].cells[${cellIndex}]`);
      technicalKey(parsed["columnKey"], `${path}.rows[${rowIndex}].cells[${cellIndex}].columnKey`);
      string(parsed["value"], `${path}.rows[${rowIndex}].cells[${cellIndex}].value`);
    });
  });
}
function validateNodeChildren(value, path, entityIds, minimumLength, maximumLength, positionPolicy, colorTokenKeys) {
  const children = array(value, path);
  if (children.length < minimumLength || children.length > maximumLength) {
    throw new RendererDocumentCodecError(
      `${path} must contain between ${minimumLength} and ${maximumLength} items`
    );
  }
  children.forEach(
    (child, index) => validateNode(child, `${path}[${index}]`, entityIds, positionPolicy, colorTokenKeys)
  );
}
function validateNode(value, path, entityIds, positionPolicy, colorTokenKeys) {
  const item = record(value, path);
  const type = literal(
    item["type"],
    ["Freeform", "Stack", "Grid", "Form", "Text", "Input", "Button", "Table", "Divider", "Badge"],
    `${path}.type`
  );
  const common = ["id", "name", "visibility", "layoutItem", "responsive", "type"];
  const fieldsByType = {
    Freeform: ["children"],
    Stack: ["direction", "gap", "align", "justify", "padding", "children"],
    Grid: ["columns", "gap", "padding", "columnOverrides", "children"],
    Form: ["formDefinitionId", "gap", "padding", "children"],
    Text: ["content", "semantic", "tone"],
    Input: [
      "label",
      "placeholder",
      "value",
      "inputType",
      "required",
      "disabled",
      "formDefinitionId",
      "formFieldId"
    ],
    Button: ["label", "variant", "size", "disabled", "iconName"],
    Table: ["columns", "rows", "density"],
    Divider: ["spacing", "tone"],
    Badge: ["label", "tone", "iconName"]
  };
  exactKeys(item, [...common, ...fieldsByType[type]], path, type === "Freeform" ? ["grids"] : []);
  validateCommon(item, path);
  const layoutItem = record(item["layoutItem"], `${path}.layoutItem`);
  const hasPosition = Object.hasOwn(layoutItem, "position");
  if (positionPolicy === "required" && !hasPosition) {
    throw new RendererDocumentCodecError(
      `${path}.layoutItem.position is required inside a Freeform container`
    );
  }
  if (positionPolicy === "forbidden" && hasPosition) {
    throw new RendererDocumentCodecError(
      `${path}.layoutItem.position is forbidden on a document or component root`
    );
  }
  registerEntityId(item["id"], `${path}.id`, entityIds);
  switch (type) {
    case "Freeform": {
      const width = record(layoutItem["width"], `${path}.layoutItem.width`);
      const height = record(layoutItem["height"], `${path}.layoutItem.height`);
      if (width["unit"] !== "px" || height["unit"] !== "px" || Number(width["value"]) <= 0 || Number(height["value"]) <= 0) {
        throw new RendererDocumentCodecError(
          `${path} Freeform width and height must be non-zero px lengths`
        );
      }
      const widthValue = Number(width["value"]);
      const heightValue = Number(height["value"]);
      validateFreeformGrids(
        item["grids"],
        `${path}.grids`,
        widthValue,
        heightValue,
        entityIds,
        colorTokenKeys
      );
      validateNodeChildren(
        item["children"],
        `${path}.children`,
        entityIds,
        0,
        500,
        "required",
        colorTokenKeys
      );
      return;
    }
    case "Stack":
      literal(item["direction"], ["row", "column"], `${path}.direction`);
      boundedInteger(item["gap"], 0, 128, `${path}.gap`);
      literal(item["align"], ["start", "center", "end", "stretch"], `${path}.align`);
      literal(item["justify"], ["start", "center", "end", "between"], `${path}.justify`);
      validatePadding(item["padding"], `${path}.padding`);
      validateNodeChildren(
        item["children"],
        `${path}.children`,
        entityIds,
        0,
        500,
        "optional",
        colorTokenKeys
      );
      return;
    case "Grid": {
      boundedInteger(item["columns"], 1, 12, `${path}.columns`);
      boundedInteger(item["gap"], 0, 128, `${path}.gap`);
      validatePadding(item["padding"], `${path}.padding`);
      const overrides = array(item["columnOverrides"], `${path}.columnOverrides`);
      if (overrides.length > 3) {
        throw new RendererDocumentCodecError(
          `${path}.columnOverrides must contain at most 3 items`
        );
      }
      let previousMinWidth = null;
      overrides.forEach((override, index) => {
        const overridePath = `${path}.columnOverrides[${index}]`;
        const parsed = record(override, overridePath);
        exactKeys(parsed, ["minWidth", "columns"], overridePath);
        const minWidth = boundedInteger(parsed["minWidth"], 320, 2560, `${overridePath}.minWidth`);
        boundedInteger(parsed["columns"], 1, 12, `${overridePath}.columns`);
        if (previousMinWidth !== null && minWidth <= previousMinWidth) {
          throw new RendererDocumentCodecError(
            `${path}.columnOverrides must use strictly increasing minWidth values`
          );
        }
        previousMinWidth = minWidth;
      });
      validateNodeChildren(
        item["children"],
        `${path}.children`,
        entityIds,
        0,
        500,
        "optional",
        colorTokenKeys
      );
      return;
    }
    case "Form":
      uuid(item["formDefinitionId"], `${path}.formDefinitionId`);
      boundedInteger(item["gap"], 0, 128, `${path}.gap`);
      validatePadding(item["padding"], `${path}.padding`);
      validateNodeChildren(
        item["children"],
        `${path}.children`,
        entityIds,
        1,
        200,
        "optional",
        colorTokenKeys
      );
      return;
    case "Text":
      string(item["content"], `${path}.content`);
      literal(
        item["semantic"],
        ["heading", "body", "label", "caption"],
        `${path}.semantic`
      );
      literal(
        item["tone"],
        ["default", "muted", "success", "warning", "danger"],
        `${path}.tone`
      );
      return;
    case "Input":
      nonEmptyString(item["label"], `${path}.label`);
      string(item["placeholder"], `${path}.placeholder`);
      string(item["value"], `${path}.value`);
      literal(item["inputType"], ["text", "number", "email"], `${path}.inputType`);
      boolean(item["required"], `${path}.required`);
      boolean(item["disabled"], `${path}.disabled`);
      if (item["formDefinitionId"] === null !== (item["formFieldId"] === null)) {
        throw new RendererDocumentCodecError(`${path} form bindings must be supplied together`);
      }
      if (item["formDefinitionId"] !== null)
        uuid(item["formDefinitionId"], `${path}.formDefinitionId`);
      if (item["formFieldId"] !== null) uuid(item["formFieldId"], `${path}.formFieldId`);
      return;
    case "Button":
      nonEmptyString(item["label"], `${path}.label`);
      literal(
        item["variant"],
        ["primary", "secondary", "danger", "ghost"],
        `${path}.variant`
      );
      literal(item["size"], ["small", "medium", "large"], `${path}.size`);
      boolean(item["disabled"], `${path}.disabled`);
      if (item["iconName"] !== null) nonEmptyString(item["iconName"], `${path}.iconName`);
      return;
    case "Divider":
      boundedInteger(item["spacing"], 0, 64, `${path}.spacing`);
      literal(item["tone"], ["default", "muted"], `${path}.tone`);
      return;
    case "Badge":
      nonEmptyString(item["label"], `${path}.label`);
      if (String(item["label"]).length > 40) {
        throw new RendererDocumentCodecError(`${path}.label must be at most 40 characters`);
      }
      literal(
        item["tone"],
        ["default", "success", "warning", "danger"],
        `${path}.tone`
      );
      if (item["iconName"] !== null) nonEmptyString(item["iconName"], `${path}.iconName`);
      return;
    case "Table":
      validateTable(item, path, entityIds);
      literal(item["density"], ["compact", "comfortable"], `${path}.density`);
  }
}
function collectNodes(node, result) {
  result.set(node.id, node);
  if (isStructuredPrototypeContainerNode(node)) {
    for (const child of node.children) collectNodes(child, result);
  }
}
function validateShell(value) {
  const shell = record(value, "document.settings.shell");
  const kind = literal(
    shell["kind"],
    ["sidebar", "topbar"],
    "document.settings.shell.kind"
  );
  const commonKeys = [
    "kind",
    "title",
    "accentColorTokenKey",
    "navigationBackgroundColorTokenKey",
    "contentBackgroundColorTokenKey",
    "surfaceColorTokenKey"
  ];
  exactKeys(
    shell,
    kind === "sidebar" ? [...commonKeys, "navigationWidth", "expandedMinWidth"] : commonKeys,
    "document.settings.shell"
  );
  boundedNonEmptyString(shell["title"], 80, "document.settings.shell.title");
  const tokenKeys = [
    technicalKey(shell["accentColorTokenKey"], "document.settings.shell.accentColorTokenKey"),
    technicalKey(
      shell["navigationBackgroundColorTokenKey"],
      "document.settings.shell.navigationBackgroundColorTokenKey"
    ),
    technicalKey(
      shell["contentBackgroundColorTokenKey"],
      "document.settings.shell.contentBackgroundColorTokenKey"
    ),
    technicalKey(shell["surfaceColorTokenKey"], "document.settings.shell.surfaceColorTokenKey")
  ];
  if (kind === "sidebar") {
    boundedInteger(shell["navigationWidth"], 160, 400, "document.settings.shell.navigationWidth");
    boundedInteger(
      shell["expandedMinWidth"],
      320,
      2560,
      "document.settings.shell.expandedMinWidth"
    );
  }
  return tokenKeys;
}
function validateGraph(document) {
  const pageIds = new Set(document.pages.map((page) => page.id));
  if (pageIds.size !== document.pages.length)
    throw new RendererDocumentCodecError("pages contain duplicate IDs");
  if (document.runtime.pageIds.length !== document.pages.length || document.runtime.pageIds.some((pageId, index) => document.pages[index]?.id !== pageId)) {
    throw new RendererDocumentCodecError("runtime page order must match document page order");
  }
  for (const item of document.navigation.items) {
    if (!pageIds.has(item.targetPageId)) {
      throw new RendererDocumentCodecError(`navigation ${item.id} references an unknown page`);
    }
  }
  const nodes = /* @__PURE__ */ new Map();
  for (const page of document.pages) collectNodes(page.root, nodes);
  for (const definition of document.componentDefinitions) collectNodes(definition.root, nodes);
  const schemasById = new Map(document.runtime.entitySchemas.map((schema) => [schema.id, schema]));
  const viewBindingTargets = /* @__PURE__ */ new Set();
  for (const binding of document.runtime.viewBindings) {
    const bindingTarget = `${binding.nodeId}:${binding.target}`;
    if (viewBindingTargets.has(bindingTarget)) {
      throw new RendererDocumentCodecError(
        `view bindings contain duplicate node target ${bindingTarget}`
      );
    }
    viewBindingTargets.add(bindingTarget);
    const node = nodes.get(binding.nodeId);
    if (node === void 0)
      throw new RendererDocumentCodecError(`view binding ${binding.id} references an unknown node`);
    if (binding.target === "tableRows" && node.type !== "Table") {
      throw new RendererDocumentCodecError(`view binding ${binding.id} requires a Table node`);
    }
    if (binding.target === "tableRows" && node.type === "Table") {
      const schema = schemasById.get(binding.schemaId);
      if (schema === void 0) {
        throw new RendererDocumentCodecError(
          `view binding ${binding.id} references an unknown schema`
        );
      }
      const schemaFieldIds = new Set(schema.fields.map((field) => field.id));
      for (const column of node.columns) {
        if (column.fieldId === null) {
          throw new RendererDocumentCodecError(
            `runtime table ${node.id} column ${column.key} requires a schema field`
          );
        }
        if (!schemaFieldIds.has(column.fieldId)) {
          throw new RendererDocumentCodecError(
            `runtime table ${node.id} column ${column.key} field is not in its binding schema`
          );
        }
      }
    }
    if (binding.target === "textContent" && node.type !== "Text") {
      throw new RendererDocumentCodecError(`view binding ${binding.id} requires a Text node`);
    }
  }
  for (const rule of document.runtime.rules) {
    const node = nodes.get(rule.trigger.nodeId);
    if (node === void 0)
      throw new RendererDocumentCodecError(`rule ${rule.id} references an unknown node`);
    if (rule.trigger.event === "rowActivated" && node.type !== "Table") {
      throw new RendererDocumentCodecError(`rule ${rule.id} row activation requires a Table node`);
    }
    if ((rule.trigger.event === "click" || rule.trigger.event === "submit") && node.type !== "Button") {
      throw new RendererDocumentCodecError(`rule ${rule.id} activation requires a Button node`);
    }
  }
}
function registerRuntimeEntityIds(runtime, entityIds) {
  runtime.roles.forEach(
    (role, index) => registerEntityId(role.id, `document.runtime.roles[${index}].id`, entityIds)
  );
  runtime.variables.forEach(
    (variable, index) => registerEntityId(variable.id, `document.runtime.variables[${index}].id`, entityIds)
  );
  runtime.entitySchemas.forEach((schema, schemaIndex) => {
    registerEntityId(schema.id, `document.runtime.entitySchemas[${schemaIndex}].id`, entityIds);
    schema.fields.forEach(
      (field, fieldIndex) => registerEntityId(
        field.id,
        `document.runtime.entitySchemas[${schemaIndex}].fields[${fieldIndex}].id`,
        entityIds
      )
    );
  });
  runtime.forms.forEach((form, formIndex) => {
    registerEntityId(form.id, `document.runtime.forms[${formIndex}].id`, entityIds);
    form.fields.forEach(
      (field, fieldIndex) => registerEntityId(
        field.id,
        `document.runtime.forms[${formIndex}].fields[${fieldIndex}].id`,
        entityIds
      )
    );
  });
  runtime.viewBindings.forEach(
    (binding, index) => registerEntityId(binding.id, `document.runtime.viewBindings[${index}].id`, entityIds)
  );
  runtime.rules.forEach(
    (rule, index) => registerEntityId(rule.id, `document.runtime.rules[${index}].id`, entityIds)
  );
  runtime.scenarios.forEach((scenario, scenarioIndex) => {
    registerEntityId(scenario.id, `document.runtime.scenarios[${scenarioIndex}].id`, entityIds);
    scenario.entityFixtures.forEach(
      (entitySet, entitySetIndex) => entitySet.entities.forEach(
        (entity, entityIndex) => registerEntityId(
          entity.id,
          `document.runtime.scenarios[${scenarioIndex}].entityFixtures[${entitySetIndex}].entities[${entityIndex}].id`,
          entityIds
        )
      )
    );
  });
}
function parseRendererDocument(value) {
  const item = record(value, "document");
  exactKeys(
    item,
    [
      "schemaVersion",
      "id",
      "title",
      "locale",
      "settings",
      "tokens",
      "componentDefinitions",
      "pages",
      "navigation",
      "flows",
      "runtime",
      "assetRefs"
    ],
    "document"
  );
  if (item["schemaVersion"] !== 1)
    throw new RendererDocumentCodecError("document.schemaVersion must equal 1");
  const entityIds = /* @__PURE__ */ new Set();
  registerEntityId(item["id"], "document.id", entityIds);
  boundedNonEmptyString(item["title"], 120, "document.title");
  literal(item["locale"], ["zh-CN", "en-US"], "document.locale");
  const settings = record(item["settings"], "document.settings");
  exactKeys(settings, ["defaultViewport", "theme", "shell"], "document.settings");
  literal(
    settings["defaultViewport"],
    ["desktop", "tablet", "mobile"],
    "document.settings.defaultViewport"
  );
  literal(settings["theme"], ["light", "dark", "system"], "document.settings.theme");
  const shellColorTokenKeys = validateShell(settings["shell"]);
  const tokens = record(item["tokens"], "document.tokens");
  exactKeys(tokens, ["colors", "spacing"], "document.tokens");
  const colorTokenKeys = /* @__PURE__ */ new Set();
  for (const group of ["colors", "spacing"]) {
    const maximumLength = group === "colors" ? 100 : 50;
    boundedArray(tokens[group], 0, maximumLength, `document.tokens.${group}`).forEach(
      (token, index) => {
        const parsed2 = record(token, `document.tokens.${group}[${index}]`);
        exactKeys(parsed2, ["key", "value"], `document.tokens.${group}[${index}]`);
        const key = technicalKey(parsed2["key"], `document.tokens.${group}[${index}].key`);
        if (group === "colors") colorTokenKeys.add(key);
        boundedNonEmptyString(parsed2["value"], 120, `document.tokens.${group}[${index}].value`);
      }
    );
  }
  const missingShellColorTokenKeys = shellColorTokenKeys.filter((key) => !colorTokenKeys.has(key));
  if (missingShellColorTokenKeys.length > 0) {
    throw new RendererDocumentCodecError(
      `document.settings.shell references unknown color token keys: ${missingShellColorTokenKeys.join(", ")}`
    );
  }
  boundedArray(item["componentDefinitions"], 0, 50, "document.componentDefinitions").forEach(
    (definition, index) => {
      const parsed2 = record(definition, `document.componentDefinitions[${index}]`);
      exactKeys(parsed2, ["id", "key", "root"], `document.componentDefinitions[${index}]`);
      registerEntityId(parsed2["id"], `document.componentDefinitions[${index}].id`, entityIds);
      technicalKey(parsed2["key"], `document.componentDefinitions[${index}].key`);
      validateNode(
        parsed2["root"],
        `document.componentDefinitions[${index}].root`,
        entityIds,
        "forbidden",
        colorTokenKeys
      );
    }
  );
  boundedArray(item["pages"], 1, 20, "document.pages").forEach((page, index) => {
    const parsed2 = record(page, `document.pages[${index}]`);
    exactKeys(
      parsed2,
      ["id", "key", "title", "route", "viewport", "root"],
      `document.pages[${index}]`
    );
    registerEntityId(parsed2["id"], `document.pages[${index}].id`, entityIds);
    technicalKey(parsed2["key"], `document.pages[${index}].key`);
    boundedNonEmptyString(parsed2["title"], 80, `document.pages[${index}].title`);
    const route = string(parsed2["route"], `document.pages[${index}].route`);
    if (!/^\/(?:[A-Za-z0-9._~-]+(?:\/[A-Za-z0-9._~-]+)*)?$/u.test(route)) {
      throw new RendererDocumentCodecError(`document.pages[${index}].route is invalid`);
    }
    const viewport = record(parsed2["viewport"], `document.pages[${index}].viewport`);
    exactKeys(viewport, ["width", "height"], `document.pages[${index}].viewport`);
    boundedInteger(viewport["width"], 320, 2560, `document.pages[${index}].viewport.width`);
    boundedInteger(viewport["height"], 480, 2160, `document.pages[${index}].viewport.height`);
    validateNode(
      parsed2["root"],
      `document.pages[${index}].root`,
      entityIds,
      "forbidden",
      colorTokenKeys
    );
  });
  const navigation = record(item["navigation"], "document.navigation");
  exactKeys(navigation, ["items"], "document.navigation");
  boundedArray(navigation["items"], 0, 20, "document.navigation.items").forEach((entry, index) => {
    const parsed2 = record(entry, `document.navigation.items[${index}]`);
    exactKeys(
      parsed2,
      ["id", "key", "label", "targetPageId"],
      `document.navigation.items[${index}]`
    );
    registerEntityId(parsed2["id"], `document.navigation.items[${index}].id`, entityIds);
    technicalKey(parsed2["key"], `document.navigation.items[${index}].key`);
    boundedNonEmptyString(parsed2["label"], 80, `document.navigation.items[${index}].label`);
    uuid(parsed2["targetPageId"], `document.navigation.items[${index}].targetPageId`);
  });
  boundedArray(item["flows"], 0, 100, "document.flows").forEach((flow, index) => {
    const parsed2 = record(flow, `document.flows[${index}]`);
    exactKeys(
      parsed2,
      ["id", "key", "ruleId", "fromNodeId", "toPageId"],
      `document.flows[${index}]`
    );
    registerEntityId(parsed2["id"], `document.flows[${index}].id`, entityIds);
    technicalKey(parsed2["key"], `document.flows[${index}].key`);
    uuid(parsed2["ruleId"], `document.flows[${index}].ruleId`);
    uuid(parsed2["fromNodeId"], `document.flows[${index}].fromNodeId`);
    if (parsed2["toPageId"] !== null) uuid(parsed2["toPageId"], `document.flows[${index}].toPageId`);
  });
  const runtime = parseRuntimeDefinition(item["runtime"]);
  registerRuntimeEntityIds(runtime, entityIds);
  boundedArray(item["assetRefs"], 0, 200, "document.assetRefs").forEach((asset, index) => {
    const parsed2 = record(asset, `document.assetRefs[${index}]`);
    exactKeys(parsed2, ["id", "contentHash", "mediaType", "alt"], `document.assetRefs[${index}]`);
    registerEntityId(parsed2["id"], `document.assetRefs[${index}].id`, entityIds);
    const hash2 = string(parsed2["contentHash"], `document.assetRefs[${index}].contentHash`);
    if (!/^sha256:[0-9a-f]{64}$/u.test(hash2))
      throw new RendererDocumentCodecError(`document.assetRefs[${index}].contentHash is invalid`);
    literal(
      parsed2["mediaType"],
      ["image/png", "image/jpeg", "image/webp", "image/svg+xml"],
      `document.assetRefs[${index}].mediaType`
    );
    string(parsed2["alt"], `document.assetRefs[${index}].alt`);
  });
  const parsed = structuredClone({ ...item, runtime });
  validateGraph(parsed);
  return parsed;
}

// scripts/prototype-renderer-worker.ts
var PROTOCOL_VERSION = "prototype-renderer-worker/v1";
var MAX_REQUEST_BYTES = 4 * 1024 * 1024;
var RendererWorkerProtocolError = class extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
    this.name = "RendererWorkerProtocolError";
  }
  code;
};
function sha256(value) {
  return `sha256:${createHash("sha256").update(value).digest("hex")}`;
}
function isRecord4(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function record2(value, path) {
  if (!isRecord4(value))
    throw new RendererWorkerProtocolError("renderer_request_invalid", `${path} must be an object`);
  return value;
}
function exactKeys2(value, keys, path) {
  const expected = new Set(keys);
  for (const key of Object.keys(value)) {
    if (!expected.has(key))
      throw new RendererWorkerProtocolError(
        "renderer_request_invalid",
        `${path} contains unknown field ${key}`
      );
  }
  for (const key of keys) {
    if (!Object.hasOwn(value, key))
      throw new RendererWorkerProtocolError(
        "renderer_request_invalid",
        `${path} is missing field ${key}`
      );
  }
}
function string2(value, path) {
  if (typeof value !== "string" || value.length === 0) {
    throw new RendererWorkerProtocolError(
      "renderer_request_invalid",
      `${path} must be a non-empty string`
    );
  }
  return value;
}
function hash(value, path) {
  const parsed = string2(value, path);
  if (!/^sha256:[0-9a-f]{64}$/u.test(parsed)) {
    throw new RendererWorkerProtocolError(
      "renderer_request_invalid",
      `${path} must be a SHA-256 hash`
    );
  }
  return parsed;
}
function inputManifest(value) {
  const item = record2(value, "inputManifest");
  exactKeys2(
    item,
    [
      "rendererVersion",
      "rendererEnvironmentVersion",
      "runtimeCoreVersion",
      "runtimeCoreSourceHash",
      "runtimeCoreBundleHash",
      "stateMachineKernelVersion",
      "renderRuntimeImageHash",
      "browserVersion",
      "fontPackHash",
      "viewportProfileHash",
      "documentObjectHash",
      "documentSchemaVersion",
      "assetObjectHashes",
      "sandboxPolicyVersion",
      "outputLocale"
    ],
    "inputManifest"
  );
  const assets = item["assetObjectHashes"];
  if (!Array.isArray(assets))
    throw new RendererWorkerProtocolError(
      "renderer_request_invalid",
      "inputManifest.assetObjectHashes must be an array"
    );
  const parsedAssets = assets.map(
    (asset, index) => hash(asset, `inputManifest.assetObjectHashes[${index}]`)
  );
  if (parsedAssets.some((asset, index) => index > 0 && (parsedAssets[index - 1] ?? "") >= asset)) {
    throw new RendererWorkerProtocolError(
      "renderer_request_invalid",
      "inputManifest.assetObjectHashes must be unique and sorted"
    );
  }
  if (item["documentSchemaVersion"] !== 1) {
    throw new RendererWorkerProtocolError(
      "renderer_schema_unsupported",
      "renderer only supports document schema version 1"
    );
  }
  const locale = item["outputLocale"];
  if (locale !== "zh-CN" && locale !== "en-US") {
    throw new RendererWorkerProtocolError(
      "renderer_request_invalid",
      "inputManifest.outputLocale is unsupported"
    );
  }
  return {
    rendererVersion: string2(item["rendererVersion"], "inputManifest.rendererVersion"),
    rendererEnvironmentVersion: string2(
      item["rendererEnvironmentVersion"],
      "inputManifest.rendererEnvironmentVersion"
    ),
    runtimeCoreVersion: string2(item["runtimeCoreVersion"], "inputManifest.runtimeCoreVersion"),
    runtimeCoreSourceHash: hash(
      item["runtimeCoreSourceHash"],
      "inputManifest.runtimeCoreSourceHash"
    ),
    runtimeCoreBundleHash: hash(
      item["runtimeCoreBundleHash"],
      "inputManifest.runtimeCoreBundleHash"
    ),
    stateMachineKernelVersion: string2(
      item["stateMachineKernelVersion"],
      "inputManifest.stateMachineKernelVersion"
    ),
    renderRuntimeImageHash: hash(
      item["renderRuntimeImageHash"],
      "inputManifest.renderRuntimeImageHash"
    ),
    browserVersion: string2(item["browserVersion"], "inputManifest.browserVersion"),
    fontPackHash: hash(item["fontPackHash"], "inputManifest.fontPackHash"),
    viewportProfileHash: hash(item["viewportProfileHash"], "inputManifest.viewportProfileHash"),
    documentObjectHash: hash(item["documentObjectHash"], "inputManifest.documentObjectHash"),
    documentSchemaVersion: 1,
    assetObjectHashes: parsedAssets,
    sandboxPolicyVersion: string2(
      item["sandboxPolicyVersion"],
      "inputManifest.sandboxPolicyVersion"
    ),
    outputLocale: locale
  };
}
function assertCompatibility(manifest) {
  const expected = {
    rendererVersion: PROTOTYPE_RENDERER_VERSION,
    rendererEnvironmentVersion: PROTOTYPE_RENDERER_ENVIRONMENT_VERSION,
    runtimeCoreVersion: RUNTIME_CORE_VERSION,
    runtimeCoreSourceHash: RUNTIME_CORE_SOURCE_HASH,
    runtimeCoreBundleHash: "sha256:3e56877d652420ad8046dfbe9336272d999e6a4d6be438619062d0863bbf5f70",
    stateMachineKernelVersion: XSTATE_KERNEL_VERSION,
    renderRuntimeImageHash: "sha256:95bad67800f8e650fde9f4da6624cbf0ca96df0348132a518e3e1a30d1f3a99b",
    browserVersion: "web-platform-es2022/1",
    fontPackHash: "sha256:40a31d8e0790e076e8e0c84e4ea00677ad866e3b0d376ea5d9341915217926ec",
    viewportProfileHash: "sha256:e4c0596cc935cd3728e5434442ab8e9d42aa649694d4cd9e969c1b95c3f09fc8",
    sandboxPolicyVersion: PROTOTYPE_RENDERER_SANDBOX_POLICY_VERSION
  };
  for (const [key, expectedValue] of Object.entries(expected)) {
    if (manifest[key] !== expectedValue) {
      throw new RendererWorkerProtocolError(
        "renderer_compatibility_mismatch",
        `inputManifest.${key} does not match the renderer compatibility row`
      );
    }
  }
}
function identity() {
  return {
    protocolVersion: PROTOCOL_VERSION,
    rendererVersion: PROTOTYPE_RENDERER_VERSION,
    rendererEnvironmentVersion: PROTOTYPE_RENDERER_ENVIRONMENT_VERSION,
    runtimeCoreVersion: RUNTIME_CORE_VERSION,
    runtimeCoreSourceHash: RUNTIME_CORE_SOURCE_HASH,
    runtimeCoreBundleHash: "sha256:3e56877d652420ad8046dfbe9336272d999e6a4d6be438619062d0863bbf5f70",
    stateMachineKernelVersion: XSTATE_KERNEL_VERSION,
    renderRuntimeImageHash: "sha256:95bad67800f8e650fde9f4da6624cbf0ca96df0348132a518e3e1a30d1f3a99b",
    browserVersion: "web-platform-es2022/1",
    fontPackHash: "sha256:40a31d8e0790e076e8e0c84e4ea00677ad866e3b0d376ea5d9341915217926ec",
    viewportProfileHash: "sha256:e4c0596cc935cd3728e5434442ab8e9d42aa649694d4cd9e969c1b95c3f09fc8",
    sandboxPolicyVersion: PROTOTYPE_RENDERER_SANDBOX_POLICY_VERSION
  };
}
function readIdentity(input) {
  let decoded;
  try {
    decoded = JSON.parse(input);
  } catch (error) {
    throw new RendererWorkerProtocolError(
      "renderer_request_invalid",
      "renderer request is not valid JSON"
    );
  }
  if (!isRecord4(decoded)) return { requestId: "unknown", action: "unknown" };
  const requestId = typeof decoded["requestId"] === "string" ? decoded["requestId"] : "unknown";
  const action = decoded["action"];
  return { requestId, action: action === "describe" || action === "render" ? action : "unknown" };
}
function render(request) {
  exactKeys2(
    request,
    ["protocolVersion", "requestId", "action", "artifactId", "inputManifest", "document"],
    "request"
  );
  if (request["protocolVersion"] !== PROTOCOL_VERSION || request["action"] !== "render") {
    throw new RendererWorkerProtocolError(
      "renderer_request_invalid",
      "renderer request identity is invalid"
    );
  }
  const requestId = string2(request["requestId"], "request.requestId");
  const artifactId = string2(request["artifactId"], "request.artifactId");
  const manifest = inputManifest(request["inputManifest"]);
  assertCompatibility(manifest);
  const documentValue = parseRendererDocument(request["document"]);
  if (documentValue.locale !== manifest.outputLocale) {
    throw new RendererWorkerProtocolError(
      "renderer_locale_mismatch",
      "document locale does not match renderer output locale"
    );
  }
  if (documentValue.assetRefs.length !== manifest.assetObjectHashes.length) {
    throw new RendererWorkerProtocolError(
      "renderer_asset_manifest_mismatch",
      "document assets do not match renderer input manifest"
    );
  }
  const documentJson = canonicalRuntimeJson(documentValue);
  if (sha256(documentJson) !== manifest.documentObjectHash) {
    throw new RendererWorkerProtocolError(
      "renderer_document_hash_mismatch",
      "document does not match renderer input manifest"
    );
  }
  const inputManifestHash = sha256(canonicalRuntimeJson(manifest));
  const rendered = renderPrototypeDocument(
    documentValue,
    documentJson,
    manifest.documentObjectHash,
    '"use strict";(()=>{function si(){if(typeof globalThis<"u")return globalThis;if(typeof self<"u")return self;if(typeof window<"u")return window;if(typeof global<"u")return global}function ai(){let t=si();if(t.__xstate__)return t.__xstate__}var Ct=t=>{if(typeof window>"u")return;let e=ai();e&&e.register(t)};var Oe=class{constructor(e){this._process=e,this._active=!1,this._current=null,this._last=null}start(){this._active=!0,this.flush()}clear(){this._current&&(this._current.next=null,this._last=this._current)}enqueue(e){let n={value:e,next:null};if(this._current){this._last.next=n,this._last=n;return}this._current=n,this._last=n,this._active&&this.flush()}flush(){for(;this._current;){let e=this._current;this._process(e.value),this._current=e.next}this._last=null}},dt=".",ui="",lt="",ci="#",di="*",Ht="xstate.init",zt="xstate.error",ot="xstate.stop";function li(t,e){return{type:`xstate.after.${t}.${e}`}}function st(t,e){return{type:`xstate.done.state.${t}`,output:e}}function fi(t,e){return{type:`xstate.done.actor.${t}`,output:e,actorId:t}}function ft(t,e){return{type:`xstate.error.actor.${t}`,error:e,actorId:t}}function qe(t){return{type:Ht,input:t}}function O(t){setTimeout(()=>{throw t})}var mi=typeof Symbol=="function"&&Symbol.observable||"@@observable";function mt(t,e){let n=Ot(t),i=Ot(e);return typeof i=="string"?typeof n=="string"?i===n:!1:typeof n=="string"?n in i:Object.keys(n).every(r=>r in i?mt(n[r],i[r]):!1)}function je(t){if(Ut(t))return t;let e=[],n="";for(let i=0;i<t.length;i++){switch(t.charCodeAt(i)){case 92:n+=t[i+1],i++;continue;case 46:e.push(n),n="";continue}n+=t[i]}return e.push(n),e}function Ot(t){if(hn(t))return t.value;if(typeof t!="string")return t;let e=je(t);return Wt(e)}function Wt(t){if(t.length===1)return t[0];let e={},n=e;for(let i=0;i<t.length-1;i++)if(i===t.length-2)n[t[i]]=t[i+1];else{let r=n;n={},r[t[i]]=n}return e}function pt(t,e){let n={},i=Object.keys(t);for(let r=0;r<i.length;r++){let o=i[r];n[o]=e(t[o],o,t,r)}return n}function Kt(t){return Ut(t)?t:[t]}function B(t){return t===void 0?[]:Kt(t)}function at(t,e,n,i){return typeof t=="function"?t({context:e,event:n,self:i}):t}function Ut(t){return Array.isArray(t)}function pi(t){return t.type.startsWith("xstate.error.actor")}function te(t){return Kt(t).map(e=>typeof e>"u"||typeof e=="string"?{target:e}:e)}function Jt(t){if(!(t===void 0||t===ui))return B(t)}function Re(t,e,n){let i=typeof t=="object",r=i?t:void 0;return{next:(i?t.next:t)?.bind(r),error:(i?t.error:e)?.bind(r),complete:(i?t.complete:n)?.bind(r)}}function ht(t,e){return`${e}.${t}`}function Se(t,e){let n=e.match(/^xstate\\.invoke\\.(\\d+)\\.(.*)/);if(!n)return t.implementations.actors[e];let[,i,r]=n,s=t.getStateNodeById(r).config.invoke;return(Array.isArray(s)?s[i]:s).src}function Gt(t,e){if(e===t||e===di)return!0;if(!e.endsWith(".*"))return!1;let n=e.split("."),i=t.split(".");for(let r=0;r<n.length;r++){let o=n[r],s=i[r];if(o==="*")return r===n.length-1;if(o!==s)return!1}return!0}function Bt(t,e){return`${t.sessionId}.${e}`}var hi=0;function Yt(t,e){let n=new Map,i=new Map,r=new WeakMap,o=new Set,s={},{clock:a,logger:u}=e,d={schedule:(c,f,p,h,y=Math.random().toString(36).slice(2))=>{let _={source:c,target:f,event:p,delay:h,id:y,startedAt:Date.now()},C=Bt(c,y);l._snapshot._scheduledEvents[C]=_;let ee=a.setTimeout(()=>{delete s[C],delete l._snapshot._scheduledEvents[C],l._relay(c,f,p)},h);s[C]=ee},cancel:(c,f)=>{let p=Bt(c,f),h=s[p];delete s[p],delete l._snapshot._scheduledEvents[p],h!==void 0&&a.clearTimeout(h)},cancelAll:c=>{for(let f in l._snapshot._scheduledEvents){let p=l._snapshot._scheduledEvents[f];p.source===c&&d.cancel(c,p.id)}}},m=c=>{if(!o.size)return;let f={...c,rootId:t.sessionId};o.forEach(p=>p.next?.(f))},l={_snapshot:{_scheduledEvents:(e?.snapshot&&e.snapshot.scheduler)??{}},_bookId:()=>`x:${hi++}`,_register:(c,f)=>(n.set(c,f),c),_unregister:c=>{n.delete(c.sessionId);let f=r.get(c);f!==void 0&&(i.delete(f),r.delete(c))},get:c=>i.get(c),getAll:()=>Object.fromEntries(i.entries()),_set:(c,f)=>{let p=i.get(c);if(p&&p!==f)throw new Error(`Actor with system ID \'${c}\' already exists.`);i.set(c,f),r.set(f,c)},inspect:c=>{let f=Re(c);return o.add(f),{unsubscribe(){o.delete(f)}}},_sendInspectionEvent:m,_relay:(c,f,p)=>{l._sendInspectionEvent({type:"@xstate.event",sourceRef:c,actorRef:f,event:p}),f._send(p)},scheduler:d,getSnapshot:()=>({_scheduledEvents:{...l._snapshot._scheduledEvents}}),start:()=>{let c=l._snapshot._scheduledEvents;l._snapshot._scheduledEvents={};for(let f in c){let{source:p,target:h,event:y,delay:_,id:C}=c[f];d.schedule(p,h,y,_,C)}},_clock:a,_logger:u};return l}var it=!1,Le=1,V=(function(t){return t[t.NotStarted=0]="NotStarted",t[t.Running=1]="Running",t[t.Stopped=2]="Stopped",t})({}),gi={clock:{setTimeout:(t,e)=>setTimeout(t,e),clearTimeout:t=>clearTimeout(t)},logger:console.log.bind(console),devTools:!1},Be=class{constructor(e,n){this.logic=e,this._snapshot=void 0,this.clock=void 0,this.options=void 0,this.id=void 0,this.mailbox=new Oe(this._process.bind(this)),this.observers=new Set,this.eventListeners=new Map,this.logger=void 0,this._processingStatus=V.NotStarted,this._parent=void 0,this._syncSnapshot=void 0,this.ref=void 0,this._actorScope=void 0,this.systemId=void 0,this.sessionId=void 0,this.system=void 0,this._doneEvent=void 0,this.src=void 0,this._deferred=[];let i={...gi,...n},{clock:r,logger:o,parent:s,syncSnapshot:a,id:u,systemId:d,inspect:m}=i;this.system=s?s.system:Yt(this,{clock:r,logger:o}),m&&!s&&this.system.inspect(Re(m)),this.sessionId=this.system._bookId(),this.id=u??this.sessionId,this.logger=n?.logger??this.system._logger,this.clock=n?.clock??this.system._clock,this._parent=s,this._syncSnapshot=a,this.options=i,this.src=i.src??e,this.ref=this,this._actorScope={self:this,id:this.id,sessionId:this.sessionId,logger:this.logger,defer:l=>{this._deferred.push(l)},system:this.system,stopChild:l=>{if(l._parent!==this)throw new Error(`Cannot stop child actor ${l.id} of ${this.id} because it is not a child`);l._stop()},emit:l=>{let c=this.eventListeners.get(l.type),f=this.eventListeners.get("*");if(!c&&!f)return;let p=[...c?c.values():[],...f?f.values():[]];for(let h of p)try{h(l)}catch(y){O(y)}},actionExecutor:l=>{let c=()=>{if(this._actorScope.system._sendInspectionEvent({type:"@xstate.action",actorRef:this,action:{type:l.type,params:l.params}}),!l.exec)return;let f=it;try{it=!0,l.exec(l.info,l.params)}finally{it=f}};this._processingStatus===V.Running?c():this._deferred.push(c)}},this.send=this.send.bind(this),this.system._sendInspectionEvent({type:"@xstate.actor",actorRef:this}),d&&(this.systemId=d,this.system._set(d,this)),this._initState(n?.snapshot??n?.state),d&&this._snapshot.status!=="active"&&this.system._unregister(this)}_initState(e){try{this._snapshot=e?this.logic.restoreSnapshot?this.logic.restoreSnapshot(e,this._actorScope):e:this.logic.getInitialSnapshot(this._actorScope,this.options?.input)}catch(n){this._snapshot={status:"error",output:void 0,error:n}}}update(e,n){this._snapshot=e;let i;for(;i=this._deferred.shift();)try{i()}catch(r){this._deferred.length=0,this._snapshot={...e,status:"error",error:r}}switch(this._snapshot.status){case"active":for(let r of this.observers)try{r.next?.(e)}catch(o){O(o)}break;case"done":for(let r of this.observers)try{r.next?.(e)}catch(o){O(o)}this._stopProcedure(),this._complete(),this._doneEvent=fi(this.id,this._snapshot.output),this._parent&&this.system._relay(this,this._parent,this._doneEvent);break;case"error":this._error(this._snapshot.error);break}this.system._sendInspectionEvent({type:"@xstate.snapshot",actorRef:this,event:n,snapshot:e})}subscribe(e,n,i){let r=Re(e,n,i);if(this._processingStatus!==V.Stopped)this.observers.add(r);else switch(this._snapshot.status){case"done":try{r.complete?.()}catch(o){O(o)}break;case"error":{let o=this._snapshot.error;if(!r.error)O(o);else try{r.error(o)}catch(s){O(s)}break}}return{unsubscribe:()=>{this.observers.delete(r)}}}on(e,n){let i=this.eventListeners.get(e);i||(i=new Set,this.eventListeners.set(e,i));let r=n.bind(void 0);return i.add(r),{unsubscribe:()=>{i.delete(r)}}}select(e,n=Object.is){return{subscribe:i=>{let r=Re(i),o=this.getSnapshot(),s=e(o);return this.subscribe(a=>{let u=e(a);n(s,u)||(s=u,r.next?.(u))})},get:()=>e(this.getSnapshot())}}start(){if(this._processingStatus===V.Running)return this;this._syncSnapshot&&this.subscribe({next:i=>{i.status==="active"&&this.system._relay(this,this._parent,{type:`xstate.snapshot.${this.id}`,snapshot:i})},error:()=>{}}),this.system._register(this.sessionId,this),this.systemId&&this.system._set(this.systemId,this),this._processingStatus=V.Running;let e=qe(this.options.input);switch(this.system._sendInspectionEvent({type:"@xstate.event",sourceRef:this._parent,actorRef:this,event:e}),this._snapshot.status){case"done":return this.update(this._snapshot,e),this;case"error":return this._error(this._snapshot.error),this}if(this._parent||this.system.start(),this.logic.start)try{this.logic.start(this._snapshot,this._actorScope)}catch(i){return this._snapshot={...this._snapshot,status:"error",error:i},this._error(i),this}return this.update(this._snapshot,e),this.options.devTools&&this.attachDevTools(),this.mailbox.start(),this}_process(e){let n,i;try{n=this.logic.transition(this._snapshot,e,this._actorScope)}catch(r){i={err:r}}if(i){let{err:r}=i;this._snapshot={...this._snapshot,status:"error",error:r},this._error(r);return}this.update(n,e),e.type===ot&&(this._stopProcedure(),this._complete())}_stop(){return this._processingStatus===V.Stopped?this:(this.mailbox.clear(),this._processingStatus===V.NotStarted?(this._processingStatus=V.Stopped,this):(this.mailbox.enqueue({type:ot}),this))}stop(){if(this._parent)throw new Error("A non-root actor cannot be stopped directly.");return this._stop()}_complete(){for(let e of this.observers)try{e.complete?.()}catch(n){O(n)}this.observers.clear(),this.eventListeners.clear()}_reportError(e){if(!this.observers.size){this._parent||O(e),this.eventListeners.clear();return}let n=!1;for(let i of this.observers){let r=i.error;n||=!r;try{r?.(e)}catch(o){O(o)}}this.observers.clear(),this.eventListeners.clear(),n&&O(e)}_error(e){this._stopProcedure(),this._reportError(e),this._parent&&this.system._relay(this,this._parent,ft(this.id,e))}_stopProcedure(){return this._processingStatus!==V.Running?this:(this.system.scheduler.cancelAll(this),this.mailbox.clear(),this.mailbox=new Oe(this._process.bind(this)),this._processingStatus=V.Stopped,this.system._unregister(this),this)}_send(e){this._processingStatus!==V.Stopped&&this.mailbox.enqueue(e)}send(e){this.system._relay(void 0,this,e)}attachDevTools(){let{devTools:e}=this.options;e&&(typeof e=="function"?e:Ct)(this)}toJSON(){return{xstate$$type:Le,id:this.id}}getPersistedSnapshot(e){return this.logic.getPersistedSnapshot(this._snapshot,e)}[mi](){return this}getSnapshot(){return this._snapshot}};function q(t,...[e]){return new Be(t,e)}function yi(t,e,n,i,{sendId:r}){let o=typeof r=="function"?r(n,i):r;return[e,{sendId:o},void 0]}function vi(t,e){t.defer(()=>{t.system.scheduler.cancel(t.self,e.sendId)})}function fe(t){function e(n,i){}return e.type="xstate.cancel",e.sendId=t,e.resolve=yi,e.execute=vi,e}function wi(t,e,n,i,{id:r,systemId:o,src:s,input:a,syncSnapshot:u}){let d=typeof s=="string"?Se(e.machine,s):s,m=typeof r=="function"?r(n):r,l,c;return d&&(c=typeof a=="function"?a({context:e.context,event:n.event,self:t.self}):a,l=q(d,{id:m,src:s,parent:t.self,syncSnapshot:u,systemId:o,input:c})),[G(e,{children:{...e.children,[m]:l}}),{id:r,systemId:o,actorRef:l,src:s,input:c},void 0]}function bi(t,{actorRef:e}){e&&t.defer(()=>{e._processingStatus!==V.Stopped&&e.start()})}function me(...[t,{id:e,systemId:n,input:i,syncSnapshot:r=!1}={}]){function o(s,a){}return o.type="xstate.spawnChild",o.id=e,o.systemId=n,o.src=t,o.input=i,o.syncSnapshot=r,o.resolve=wi,o.execute=bi,o}function $i(t,e,n,i,{actorRef:r}){let o=typeof r=="function"?r(n,i):r,s=typeof o=="string"?e.children[o]:o,a=e.children;return s&&(a={...a},delete a[s.id]),[G(e,{children:a}),s,void 0]}function Xt(t,e){let n=e.getSnapshot();if(n&&"children"in n)for(let i of Object.values(n.children))Xt(t,i);t.system._unregister(e)}function Ri(t,e){if(e){if(Xt(t,e),e._processingStatus!==V.Running){t.stopChild(e);return}t.defer(()=>{t.stopChild(e)})}}function re(t){function e(n,i){}return e.type="xstate.stopChild",e.actorRef=t,e.resolve=$i,e.execute=Ri,e}function Ii(t,{context:e,event:n},{guards:i}){return i.every(r=>oe(r,e,n,t))}function Zt(t){function e(n,i){return!1}return e.check=Ii,e.guards=t,e}function oe(t,e,n,i){let{machine:r}=i,o=typeof t=="function",s=o?t:r.implementations.guards[typeof t=="string"?t:t.type];if(!o&&!s)throw new Error(`Guard \'${typeof t=="string"?t:t.type}\' is not implemented.\'.`);if(typeof s!="function")return oe(s,e,n,i);let a={context:e,event:n},u=o||typeof t=="string"?void 0:"params"in t?typeof t.params=="function"?t.params({context:e,event:n}):t.params:void 0;return"check"in s?s.check(i,a,s):s(a,u)}function He(t){return t.type==="atomic"||t.type==="final"}function de(t){return Object.values(t.states).filter(e=>e.type!=="history")}function pe(t,e){let n=[];if(e===t)return n;let i=t.parent;for(;i&&i!==e;)n.push(i),i=i.parent;return n}function xe(t){let e=new Set(t),n=en(e);for(let i of e)if(i.type==="compound"&&(!n.get(i)||!n.get(i).length))qt(i).forEach(r=>e.add(r));else if(i.type==="parallel"){for(let r of de(i))if(r.type!=="history"&&!e.has(r)){let o=qt(r);for(let s of o)e.add(s)}}for(let i of e){let r=i.parent;for(;r;)e.add(r),r=r.parent}return e}function Qt(t,e){let n=e.get(t);if(!n)return{};if(t.type==="compound"){let r=n[0];if(r){if(He(r))return r.key}else return{}}let i={};for(let r of n)i[r.key]=Qt(r,e);return i}function en(t){let e=new Map;for(let n of t)e.has(n)||e.set(n,[]),n.parent&&(e.has(n.parent)||e.set(n.parent,[]),e.get(n.parent).push(n));return e}function tn(t,e){let n=xe(e);return Qt(t,en(n))}function ze(t,e){return e.type==="compound"?de(e).some(n=>n.type==="final"&&t.has(n)):e.type==="parallel"?de(e).every(n=>ze(t,n)):e.type==="final"}var ke=t=>t[0]===ci;function nn(t,e){let n=t.transitions.get(e),i=[...t.transitions.keys()].filter(r=>r!==e&&Gt(e,r)).sort((r,o)=>o.length-r.length).flatMap(r=>t.transitions.get(r));return n?[...n,...i]:i}function rn(t){let e=t.config.after;if(!e)return[];let n=r=>{let o=li(r,t.id),s=o.type;return t.entry.push(ge(o,{id:s,delay:r})),t.exit.push(fe(s)),s};return Object.keys(e).flatMap(r=>{let o=e[r],s=typeof o=="string"?{target:o}:o,a=Number.isNaN(+r)?r:+r,u=n(a);return B(s).map(d=>({...d,event:u,delay:a}))}).map(r=>{let{delay:o}=r;return{...z(t,r.event,r),delay:o}})}function z(t,e,n){let i=Jt(n.target),r=n.reenter??!1,o=Si(t,i),s={...n,actions:B(n.actions),guard:n.guard,target:o,source:t,reenter:r,eventType:e,toJSON:()=>({...s,source:`#${t.id}`,target:o?o.map(a=>`#${a.id}`):void 0})};return s}function on(t){let e=new Map;if(t.config.on)for(let n of Object.keys(t.config.on)){if(n===lt)throw new Error(\'Null events ("") cannot be specified as a transition key. Use `always: { ... }` instead.\');let i=t.config.on[n];e.set(n,te(i).map(r=>z(t,n,r)))}if(t.config.onDone){let n=`xstate.done.state.${t.id}`;e.set(n,te(t.config.onDone).map(i=>z(t,n,i)))}for(let n of t.invoke){if(n.onDone){let i=`xstate.done.actor.${n.id}`;e.set(i,te(n.onDone).map(r=>z(t,i,r)))}if(n.onError){let i=`xstate.error.actor.${n.id}`;e.set(i,te(n.onError).map(r=>z(t,i,r)))}if(n.onSnapshot){let i=`xstate.snapshot.${n.id}`;e.set(i,te(n.onSnapshot).map(r=>z(t,i,r)))}}for(let n of t.after){let i=e.get(n.eventType);i||(i=[],e.set(n.eventType,i)),i.push(n)}return e}function sn(t){let e=[],n=i=>{Object.values(i).forEach(r=>{if(r.config.route&&r.config.id){let o=r.config.id,s=r.config.route.guard,a=({event:d})=>d.to===`#${o}`,u={...r.config.route,guard:s?Zt([a,s]):a,target:`#${o}`};e.push(z(t,"xstate.route",u))}r.states&&n(r.states)})};n(t.states),e.length>0&&t.transitions.set("xstate.route",e)}function an(t,e){let n=typeof e=="string"?t.states[e]:e?t.states[e.target]:void 0;if(!n&&e)throw new Error(`Initial state node "${e}" not found on parent state node #${t.id}`);let i={source:t,actions:!e||typeof e=="string"?[]:B(e.actions),eventType:null,reenter:!1,target:n?[n]:[],toJSON:()=>({...i,source:`#${t.id}`,target:n?[`#${n.id}`]:[]})};return i}function Si(t,e){if(e!==void 0)return e.map(n=>{if(typeof n!="string")return n;if(ke(n))return t.machine.getStateNodeById(n);let i=n[0]===dt;if(i&&!t.parent)return Ie(t,n.slice(1));let r=i?t.key+n:n;if(t.parent)try{return Ie(t.parent,r)}catch(o){throw new Error(`Invalid transition definition for state node \'${t.id}\':\n${o.message}`)}else throw new Error(`Invalid target: "${n}" is not a valid target from the root node. Did you mean ".${n}"?`)})}function un(t){let e=Jt(t.config.target);return e?{target:e.map(n=>typeof n=="string"?Ie(t.parent,n):n)}:t.parent.type==="parallel"?{target:[t.parent]}:t.parent.initial}function ne(t){return t.type==="history"}function qt(t){let e=cn(t);for(let n of e)for(let i of pe(n,t))e.add(i);return e}function cn(t){let e=new Set;function n(i){if(!e.has(i)){if(e.add(i),i.type==="compound")n(i.initial.target[0]);else if(i.type==="parallel")for(let r of de(i))n(r)}}return n(t),e}function le(t,e){if(ke(e))return t.machine.getStateNodeById(e);if(!t.states)throw new Error(`Unable to retrieve child state \'${e}\' from \'${t.id}\'; no child states exist.`);let n=t.states[e];if(!n)throw new Error(`Child state \'${e}\' does not exist on \'${t.id}\'`);return n}function Ie(t,e){if(typeof e=="string"&&ke(e))try{return t.machine.getStateNodeById(e)}catch{}let n=je(e).slice(),i=t;for(;n.length;){let r=n.shift();if(!r.length)break;i=le(i,r)}return i}function he(t,e){if(typeof e=="string"){let r=t.states[e];if(!r)throw new Error(`State \'${e}\' does not exist on \'${t.id}\'`);return[t,r]}let n=Object.keys(e),i=n.map(r=>le(t,r)).filter(Boolean);return[t.machine.root,t].concat(i,n.reduce((r,o)=>{let s=le(t,o);if(!s)return r;let a=he(s,e[o]);return r.concat(a)},[]))}function xi(t,e,n,i){let o=le(t,e).next(n,i);return!o||!o.length?t.next(n,i):o}function ki(t,e,n,i){let r=Object.keys(e),o=le(t,r[0]),s=We(o,e[r[0]],n,i);return!s||!s.length?t.next(n,i):s}function Ei(t,e,n,i){let r=[];for(let o of Object.keys(e)){let s=e[o];if(!s)continue;let a=le(t,o),u=We(a,s,n,i);u&&r.push(...u)}return r.length?r:t.next(n,i)}function We(t,e,n,i){return typeof e=="string"?xi(t,e,n,i):Object.keys(e).length===1?ki(t,e,n,i):Ei(t,e,n,i)}function _i(t){return Object.keys(t.states).map(e=>t.states[e]).filter(e=>e.type==="history")}function J(t,e){let n=t;for(;n.parent&&n.parent!==e;)n=n.parent;return n.parent===e}function Ti(t,e){let n=new Set(t),i=new Set(e);for(let r of n)if(i.has(r))return!0;for(let r of i)if(n.has(r))return!0;return!1}function dn(t,e,n){let i=new Set;for(let r of t){let o=!1,s=new Set;for(let a of i)if(Ti(ut([r],e,n),ut([a],e,n)))if(J(r.source,a.source))s.add(a);else{o=!0;break}if(!o){for(let a of s)i.delete(a);i.add(r)}}return Array.from(i)}function Vi(t){let[e,...n]=t;for(let i of pe(e,void 0))if(n.every(r=>J(r,i)))return i}function gt(t,e){if(!t.target)return[];let n=new Set;for(let i of t.target)if(ne(i))if(e[i.id])for(let r of e[i.id])n.add(r);else for(let r of gt(un(i),e))n.add(r);else n.add(i);return[...n]}function ln(t,e){let n=gt(t,e);if(!n)return;if(!t.reenter&&n.every(r=>r===t.source||J(r,t.source)))return t.source;let i=Vi(n.concat(t.source));if(i)return i;if(!t.reenter)return t.source.machine.root}function ut(t,e,n){let i=new Set;for(let r of t)if(r.target?.length){let o=ln(r,n);r.reenter&&r.source===o&&i.add(o);for(let s of e)J(s,o)&&i.add(s)}return[...i]}function Pi(t,e){if(t.length!==e.size)return!1;for(let n of t)if(!e.has(n))return!1;return!0}function yt(t,e,n,i,r){return ct([{target:[...cn(t)],source:t,reenter:!0,actions:[],eventType:null,toJSON:null}],e,n,i,!0,r)}function ct(t,e,n,i,r,o){let s=[];if(!t.length)return[e,s];let a=n.actionExecutor;n.actionExecutor=u=>{s.push(u),a(u)};try{let u=new Set(e._nodes),d=e.historyValue,m=dn(t,u,d),l=e;r||([l,d]=Di(l,i,n,m,u,d,o,n.actionExecutor)),l=ie(l,i,n,m.flatMap(f=>f.actions),o,void 0),l=Ai(l,i,n,m,u,o,d,r);let c=[...u];l.status==="done"&&(l=ie(l,i,n,c.sort((f,p)=>p.order-f.order).flatMap(f=>f.exit),o,void 0));try{return d===e.historyValue&&Pi(e._nodes,u)?[l,s]:[G(l,{_nodes:c,historyValue:d}),s]}catch(f){throw f}}finally{n.actionExecutor=a}}function Ni(t,e,n,i,r){if(i.output===void 0)return;let o=st(r.id,r.output!==void 0&&r.parent?at(r.output,t.context,e,n.self):void 0);return at(i.output,t.context,o,n.self)}function Ai(t,e,n,i,r,o,s,a){let u=t,d=new Set,m=new Set;Fi(i,s,m,d),a&&m.add(t.machine.root);let l=new Set;for(let c of[...d].sort((f,p)=>f.order-p.order)){r.add(c);let f=[];f.push(...c.entry);for(let p of c.invoke)f.push(me(p.src,{...p,syncSnapshot:!!p.onSnapshot}));if(m.has(c)){let p=c.initial.actions;f.push(...p)}if(u=ie(u,e,n,f,o,c.invoke.map(p=>p.id)),c.type==="final"){let p=c.parent,h=p?.type==="parallel"?p:p?.parent,y=h||c;for(p?.type==="compound"&&o.push(st(p.id,c.output!==void 0?at(c.output,u.context,e,n.self):void 0));h?.type==="parallel"&&!l.has(h)&&ze(r,h);)l.add(h),o.push(st(h.id)),y=h,h=h.parent;if(h)continue;u=G(u,{status:"done",output:Ni(u,e,n,u.machine.root,y)})}}return u}function Fi(t,e,n,i){for(let r of t){let o=ln(r,e);for(let a of r.target||[])!ne(a)&&(r.source!==a||r.source!==o||r.reenter)&&(i.add(a),n.add(a)),ce(a,e,n,i);let s=gt(r,e);for(let a of s){let u=pe(a,o);o?.type==="parallel"&&u.push(o),fn(i,e,n,u,!r.source.parent&&r.reenter?void 0:o)}}}function ce(t,e,n,i){if(ne(t))if(e[t.id]){let r=e[t.id];for(let o of r)i.add(o),ce(o,e,n,i);for(let o of r)rt(o,t.parent,i,e,n)}else{let r=un(t);for(let o of r.target)i.add(o),r===t.parent?.initial&&n.add(t.parent),ce(o,e,n,i);for(let o of r.target)rt(o,t.parent,i,e,n)}else if(t.type==="compound"){let[r]=t.initial.target;ne(r)||(i.add(r),n.add(r)),ce(r,e,n,i),rt(r,t,i,e,n)}else if(t.type==="parallel")for(let r of de(t).filter(o=>!ne(o)))[...i].some(o=>J(o,r))||(ne(r)||(i.add(r),n.add(r)),ce(r,e,n,i))}function fn(t,e,n,i,r){for(let o of i)if((!r||J(o,r))&&t.add(o),o.type==="parallel")for(let s of de(o).filter(a=>!ne(a)))[...t].some(a=>J(a,s))||(t.add(s),ce(s,e,n,t))}function rt(t,e,n,i,r){fn(n,i,r,pe(t,e))}function Di(t,e,n,i,r,o,s,a){let u=t,d=ut(i,r,o);d.sort((l,c)=>c.order-l.order);let m;for(let l of d)for(let c of _i(l)){let f;c.history==="deep"?f=p=>He(p)&&J(p,l):f=p=>p.parent===l,m??={...o},m[c.id]=Array.from(r).filter(f)}for(let l of d)u=ie(u,e,n,[...l.exit,...l.invoke.map(c=>re(c.id))],s,void 0),r.delete(l);return[u,m||o]}function Mi(t,e){return t.implementations.actions[e]}function mn(t,e,n,i,r,o){let{machine:s}=t,a=t;for(let u of i){let d=typeof u=="function",m=d?u:Mi(s,typeof u=="string"?u:u.type),l={context:a.context,event:e,self:n.self,system:n.system},c=d||typeof u=="string"?void 0:"params"in u?typeof u.params=="function"?u.params({context:a.context,event:e}):u.params:void 0;if(!m||!("resolve"in m)){n.actionExecutor({type:typeof u=="string"?u:typeof u=="object"?u.type:u.name||"(anonymous)",info:l,params:c,exec:m});continue}let f=m,[p,h,y]=f.resolve(n,a,l,c,m,r);a=p,"retryResolve"in f&&o?.push([f,h]),"execute"in f&&n.actionExecutor({type:f.type,info:l,params:h,exec:f.execute.bind(null,n,h)}),y&&(a=mn(a,e,n,y,r,o))}return a}function ie(t,e,n,i,r,o){let s=o?[]:void 0,a=mn(t,e,n,i,{internalQueue:r,deferredActorIds:o},s);return s?.forEach(([u,d])=>{u.retryResolve(n,a,d)}),a}function Ee(t,e,n,i){let r=t,o=[];function s(l,c,f){n.system._sendInspectionEvent({type:"@xstate.microstep",actorRef:n.self,event:c,snapshot:l[0],_transitions:f}),o.push(l)}if(e.type===ot)return r=G(jt(r,e,n),{status:"stopped"}),s([r,[]],e,[]),{snapshot:r,microsteps:o};let a=e;if(a.type!==Ht){let l=a,c=pi(l),f=Lt(l,r);if(c&&!f.length)return r=G(t,{status:"error",error:l.error}),s([r,[]],l,[]),{snapshot:r,microsteps:o};let p=ct(f,t,n,a,!1,i);r=p[0],s(p,l,f)}let u=!0,d=t.machine.options?.maxIterations??1/0,m=0;for(;r.status==="active";){if(m++,m>d)throw new Error(`Infinite loop detected: the machine has processed more than ${d} microsteps without reaching a stable state. This usually happens when there\'s a cycle of transitions (e.g., eventless transitions or raised events causing state A -> B -> C -> A).`);let l=u?Ci(r,a):[],c=l.length?r:void 0;if(!l.length){if(!i.length)break;a=i.shift(),l=Lt(a,r)}let f=ct(l,r,n,a,!1,i);r=f[0],u=r!==c,s(f,a,l)}return r.status!=="active"&&jt(r,a,n),{snapshot:r,microsteps:o}}function jt(t,e,n){return ie(t,e,n,Object.values(t.children).map(i=>re(i)),[],void 0)}function Lt(t,e){return e.machine.getTransitionData(e,t)}function Ci(t,e){let n=new Set,i=t._nodes.filter(He);for(let r of i)e:for(let o of[r].concat(pe(r,void 0)))if(o.always){for(let s of o.always)if(s.guard===void 0||oe(s.guard,t.context,e,t)){n.add(s);break e}}return dn(Array.from(n),new Set(t._nodes),t.historyValue)}function pn(t,e){let n=xe(he(t,e));return tn(t,[...n])}function hn(t){return!!t&&typeof t=="object"&&"machine"in t&&"value"in t}var Oi=function(e){return mt(e,this.value)},Bi=function(e){return this.tags.has(e)},qi=function(e){let n=this.machine.getTransitionData(this,e);return!!n?.length&&n.some(i=>i.target!==void 0||i.actions.length)},ji=function(){let{_nodes:e,tags:n,machine:i,getMeta:r,toJSON:o,can:s,hasTag:a,matches:u,...d}=this;return{...d,tags:Array.from(n)}},Li=function(){return this._nodes.reduce((e,n)=>(n.meta!==void 0&&(e[n.id]=n.meta),e),{})};function _e(t,e){return{status:t.status,output:t.output,error:t.error,machine:e,context:t.context,_nodes:t._nodes,value:tn(e.root,t._nodes),tags:new Set(t._nodes.flatMap(n=>n.tags)),children:t.children,historyValue:t.historyValue||{},matches:Oi,hasTag:Bi,can:qi,getMeta:Li,toJSON:ji}}function G(t,e={}){return _e({...t,...e},t.machine)}function Hi(t){if(typeof t!="object"||t===null)return{};let e={};for(let n in t){let i=t[n];Array.isArray(i)&&(e[n]=i.map(r=>({id:r.id})))}return e}function gn(t,e){let{_nodes:n,tags:i,machine:r,children:o,context:s,can:a,hasTag:u,matches:d,getMeta:m,toJSON:l,...c}=t,f={};for(let h in o){let y=o[h];f[h]={snapshot:y.getPersistedSnapshot(e),src:y.src,systemId:y.systemId,syncSnapshot:y._syncSnapshot}}return{...c,context:yn(s),children:f,historyValue:Hi(c.historyValue)}}function yn(t){let e;for(let n in t){let i=t[n];if(i&&typeof i=="object")if("sessionId"in i&&"send"in i&&"ref"in i)e??=Array.isArray(t)?t.slice():{...t},e[n]={xstate$$type:Le,id:i.id};else{let r=yn(i);r!==i&&(e??=Array.isArray(t)?t.slice():{...t},e[n]=r)}}return e??t}function zi(t,e,n,i,{event:r,id:o,delay:s},{internalQueue:a}){let u=e.machine.implementations.delays;if(typeof r=="string")throw new Error(`Only event objects may be used with raise; use raise({ type: "${r}" }) instead`);let d=typeof r=="function"?r(n,i):r,m;if(typeof s=="string"){let l=u&&u[s];m=typeof l=="function"?l(n,i):l}else m=typeof s=="function"?s(n,i):s;return typeof m!="number"&&a.push(d),[e,{event:d,id:o,delay:m},void 0]}function Wi(t,e){let{event:n,delay:i,id:r}=e;if(typeof i=="number"){t.defer(()=>{let o=t.self;t.system.scheduler.schedule(o,o,n,i,r)});return}}function ge(t,e){function n(i,r){}return n.type="xstate.raise",n.event=t,n.id=e?.id,n.delay=e?.delay,n.resolve=zi,n.execute=Wi,n}function Ki(t,{machine:e,context:n},i,r){let o=(s,a)=>{if(typeof s=="string"){let u=Se(e,s);if(!u)throw new Error(`Actor logic \'${s}\' not implemented in machine \'${e.id}\'`);let d=q(u,{id:a?.id,parent:t.self,syncSnapshot:a?.syncSnapshot,input:typeof a?.input=="function"?a.input({context:n,event:i,self:t.self}):a?.input,src:s,systemId:a?.systemId});return r[d.id]=d,d}else return q(s,{id:a?.id,parent:t.self,syncSnapshot:a?.syncSnapshot,input:a?.input,src:s,systemId:a?.systemId})};return(s,a)=>{let u=o(s,a);return r[u.id]=u,t.defer(()=>{u._processingStatus!==V.Stopped&&u.start()}),u}}function Ui(t,e,n,i,{assignment:r}){if(!e.context)throw new Error("Cannot assign to undefined `context`. Ensure that `context` is defined in the machine config.");let o={},s={context:e.context,event:n.event,spawn:Ki(t,e,n.event,o),self:t.self,system:t.system},a={};if(typeof r=="function")a=r(s,i);else for(let d of Object.keys(r)){let m=r[d];a[d]=typeof m=="function"?m(s,i):m}let u=Object.assign({},e.context,a);return[G(e,{context:u,children:Object.keys(o).length?{...e.children,...o}:e.children}),void 0,void 0]}function W(t){function e(n,i){}return e.type="xstate.assign",e.assignment=t,e.resolve=Ui,e}var vn=new WeakMap;function ye(t,e,n){let i=vn.get(t);return i?e in i||(i[e]=n()):(i={[e]:n()},vn.set(t,i)),i[e]}var Ji={},Te=t=>typeof t=="string"?{type:t}:typeof t=="function"?"resolve"in t?{type:t.type}:{type:t.name}:t,Ke=class t{constructor(e,n){if(this.config=e,this.key=void 0,this.id=void 0,this.type=void 0,this.path=void 0,this.states=void 0,this.history=void 0,this.entry=void 0,this.exit=void 0,this.parent=void 0,this.machine=void 0,this.meta=void 0,this.output=void 0,this.order=-1,this.description=void 0,this.tags=[],this.transitions=void 0,this.always=void 0,this.parent=n._parent,this.key=n._key,this.machine=n._machine,this.path=this.parent?this.parent.path.concat(this.key):[],this.id=this.config.id||[this.machine.id,...this.path].join(dt),this.type=this.config.type||(this.config.states&&Object.keys(this.config.states).length?"compound":this.config.history?"history":"atomic"),this.description=this.config.description,this.order=this.machine.idMap.size,this.machine.idMap.set(this.id,this),this.states=this.config.states?pt(this.config.states,(i,r)=>new t(i,{_parent:this,_key:r,_machine:this.machine})):Ji,this.type==="compound"&&!this.config.initial)throw new Error(`No initial state specified for compound state node "#${this.id}". Try adding { initial: "${Object.keys(this.states)[0]}" } to the state config.`);this.history=this.config.history===!0?"shallow":this.config.history||!1,this.entry=B(this.config.entry).slice(),this.exit=B(this.config.exit).slice(),this.meta=this.config.meta,this.output=this.type==="final"||!this.parent?this.config.output:void 0,this.tags=B(e.tags).slice()}_initialize(){this.transitions=on(this),this.config.always&&(this.always=te(this.config.always).map(e=>z(this,lt,e))),Object.keys(this.states).forEach(e=>{this.states[e]._initialize()})}get definition(){return{id:this.id,key:this.key,version:this.machine.version,type:this.type,initial:this.initial?{target:this.initial.target,source:this,actions:this.initial.actions.map(Te),eventType:null,reenter:!1,toJSON:()=>({target:this.initial.target.map(e=>`#${e.id}`),source:`#${this.id}`,actions:this.initial.actions.map(Te),eventType:null})}:void 0,history:this.history,states:pt(this.states,e=>e.definition),on:this.on,transitions:[...this.transitions.values()].flat().map(e=>({...e,actions:e.actions.map(Te)})),entry:this.entry.map(Te),exit:this.exit.map(Te),meta:this.meta,order:this.order||-1,output:this.output,invoke:this.invoke,description:this.description,tags:this.tags}}toJSON(){return this.definition}get invoke(){return ye(this,"invoke",()=>B(this.config.invoke).map((e,n)=>{let{src:i,systemId:r}=e,o=e.id??ht(this.id,n),s=typeof i=="string"?i:`xstate.invoke.${ht(this.id,n)}`;return{...e,src:s,id:o,systemId:r,toJSON(){let{onDone:a,onError:u,...d}=e;return{...d,type:"xstate.invoke",src:s,id:o}}}}))}get on(){return ye(this,"on",()=>[...this.transitions].flatMap(([n,i])=>i.map(r=>[n,r])).reduce((n,[i,r])=>(n[i]=n[i]||[],n[i].push(r),n),{}))}get after(){return ye(this,"delayedTransitions",()=>rn(this))}get initial(){return ye(this,"initial",()=>an(this,this.config.initial))}next(e,n){let i=n.type,r=[],o,s=ye(this,`candidates-${i}`,()=>nn(this,i));for(let a of s){let{guard:u}=a,d=e.context,m=!1;try{m=!u||oe(u,d,n,e)}catch(l){let c=typeof u=="string"?u:typeof u=="object"?u.type:void 0;throw new Error(`Unable to evaluate guard ${c?`\'${c}\' `:""}in transition for event \'${i}\' in state node \'${this.id}\':\n${l.message}`)}if(m){r.push(...a.actions),o=a;break}}return o?[o]:void 0}get events(){return ye(this,"events",()=>{let{states:e}=this,n=new Set(this.ownEvents);if(e)for(let i of Object.keys(e)){let r=e[i];if(r.states)for(let o of r.events)n.add(`${o}`)}return Array.from(n)})}get ownEvents(){let e=Object.keys(Object.fromEntries(this.transitions)),n=new Set(e.filter(i=>this.transitions.get(i).some(r=>!(!r.target&&!r.actions.length&&!r.reenter))));return Array.from(n)}},Gi="#",Ue=class t{constructor(e,n){this.config=e,this.version=void 0,this.schemas=void 0,this.implementations=void 0,this.options=void 0,this.__xstatenode=!0,this.idMap=new Map,this.root=void 0,this.id=void 0,this.states=void 0,this.events=void 0,this.id=e.id||"(machine)",this.implementations={actors:n?.actors??{},actions:n?.actions??{},delays:n?.delays??{},guards:n?.guards??{}},this.version=this.config.version,this.schemas=this.config.schemas,this.options={maxIterations:1/0,...this.config.options},this.transition=this.transition.bind(this),this.getInitialSnapshot=this.getInitialSnapshot.bind(this),this.getPersistedSnapshot=this.getPersistedSnapshot.bind(this),this.restoreSnapshot=this.restoreSnapshot.bind(this),this.start=this.start.bind(this),this.root=new Ke(e,{_key:this.id,_machine:this}),this.root._initialize(),sn(this.root),this.states=this.root.states,this.events=this.root.events}provide(e){let{actions:n,guards:i,actors:r,delays:o}=this.implementations;return new t(this.config,{actions:{...n,...e.actions},guards:{...i,...e.guards},actors:{...r,...e.actors},delays:{...o,...e.delays}})}resolveState(e){let n=pn(this.root,e.value),i=xe(he(this.root,n));return _e({_nodes:[...i],context:e.context||{},children:{},status:ze(i,this.root)?"done":e.status||"active",output:e.output,error:e.error,historyValue:e.historyValue},this)}transition(e,n,i){return Ee(e,n,i,[]).snapshot}microstep(e,n,i){return Ee(e,n,i,[]).microsteps.map(([r])=>r)}getTransitionData(e,n){return We(this.root,e.value,e,n)||[]}_getPreInitialState(e,n,i){let{context:r}=this.config,o=_e({context:typeof r!="function"&&r?r:{},_nodes:[this.root],children:{},status:"active"},this);return typeof r=="function"?ie(o,n,e,[W(({spawn:a,event:u,self:d})=>r({spawn:a,input:u.input,self:d}))],i,void 0):o}getInitialSnapshot(e,n){let i=qe(n),r=[],o=this._getPreInitialState(e,i,r),[s]=yt(this.root,o,e,i,r),{snapshot:a}=Ee(s,i,e,r);return a}start(e){Object.values(e.children).forEach(n=>{n.getSnapshot().status==="active"&&n.start()})}getStateNodeById(e){let n=je(e),i=n.slice(1),r=ke(n[0])?n[0].slice(Gi.length):n[0],o=this.idMap.get(r);if(!o)throw new Error(`Child state node \'#${r}\' does not exist on machine \'${this.id}\'`);return Ie(o,i)}get definition(){return this.root.definition}toJSON(){return this.definition}getPersistedSnapshot(e,n){return gn(e,n)}restoreSnapshot(e,n){let i={},r=e.children;Object.keys(r).forEach(l=>{let c=r[l],f=c.snapshot,p=c.src,h=typeof p=="string"?Se(this,p):p;if(!h)return;let y=q(h,{id:l,parent:n.self,syncSnapshot:c.syncSnapshot,snapshot:f,src:p,systemId:c.systemId});i[l]=y});function o(l,c){if(c instanceof Ke)return c;try{return l.machine.getStateNodeById(c.id)}catch{}}function s(l,c){if(!c||typeof c!="object")return{};let f={};for(let p in c){let h=c[p];for(let y of h){let _=o(l,y);_&&(f[p]??=[],f[p].push(_))}}return f}let a=s(this.root,e.historyValue),u=_e({...e,children:i,_nodes:Array.from(xe(he(this.root,e.value))),historyValue:a},this),d=new Set;function m(l,c){if(!d.has(l)){d.add(l);for(let f in l){let p=l[f];if(p&&typeof p=="object"){if("xstate$$type"in p&&p.xstate$$type===Le){l[f]=c[p.id];continue}m(p,c)}}}}return m(u.context,i),u}};function Yi(t,e,n,i,{event:r}){let o=typeof r=="function"?r(n,i):r;return[e,{event:o},void 0]}function Xi(t,{event:e}){t.defer(()=>t.emit(e))}function wt(t){function e(n,i){}return e.type="xstate.emit",e.event=t,e.resolve=Yi,e.execute=Xi,e}var vt=(function(t){return t.Parent="#_parent",t.Internal="#_internal",t})({});function Zi(t,e,n,i,{to:r,event:o,id:s,delay:a},u){let d=e.machine.implementations.delays;if(typeof o=="string")throw new Error(`Only event objects may be used with sendTo; use sendTo({ type: "${o}" }) instead`);let m=typeof o=="function"?o(n,i):o,l;if(typeof a=="string"){let p=d&&d[a];l=typeof p=="function"?p(n,i):p}else l=typeof a=="function"?a(n,i):a;let c=typeof r=="function"?r(n,i):r,f;if(typeof c=="string"){if(c===vt.Parent?f=t.self._parent:c===vt.Internal?f=t.self:c.startsWith("#_")?f=e.children[c.slice(2)]:f=u.deferredActorIds?.includes(c)?c:e.children[c],!f)throw new Error(`Unable to send event to actor \'${c}\' from machine \'${e.machine.id}\'.`)}else f=c||t.self;return[e,{to:f,targetId:typeof c=="string"?c:void 0,event:m,id:s,delay:l},void 0]}function Qi(t,e,n){typeof n.to=="string"&&(n.to=e.children[n.to])}function er(t,e){t.defer(()=>{let{to:n,event:i,delay:r,id:o}=e;if(typeof r=="number"){t.system.scheduler.schedule(t.self,n,i,r,o);return}t.system._relay(t.self,n,i.type===zt?ft(t.self.id,i.data):i)})}function Je(t,e,n){function i(r,o){}return i.type="xstate.sendTo",i.to=t,i.event=e,i.id=n?.id,i.delay=n?.delay,i.resolve=Zi,i.retryResolve=Qi,i.execute=er,i}function tr(t,e){return Je(vt.Parent,t,e)}function nr(t,e,n,i,{collect:r}){let o=[],s=function(u){o.push(u)};return s.assign=(...a)=>{o.push(W(...a))},s.cancel=(...a)=>{o.push(fe(...a))},s.raise=(...a)=>{o.push(ge(...a))},s.sendTo=(...a)=>{o.push(Je(...a))},s.sendParent=(...a)=>{o.push(tr(...a))},s.spawnChild=(...a)=>{o.push(me(...a))},s.stopChild=(...a)=>{o.push(re(...a))},s.emit=(...a)=>{o.push(wt(...a))},r({context:n.context,event:n.event,enqueue:s,check:a=>oe(a,e.context,n.event,e),self:t.self,system:t.system},i),[e,void 0,o]}function wn(t){function e(n,i){}return e.type="xstate.enqueueActions",e.collect=t,e.resolve=nr,e}function ir(t,e,n,i,{value:r,label:o}){return[e,{value:typeof r=="function"?r(n,i):r,label:o},void 0]}function rr({logger:t},{value:e,label:n}){n?t(n,e):t(e)}function bn(t=({context:n,event:i})=>({context:n,event:i}),e){function n(i,r){}return n.type="xstate.log",n.value=t,n.label=e,n.resolve=ir,n.execute=rr,n}function or(t,e){return new Ue(t,e)}function bt({schemas:t,actors:e,actions:n,guards:i,delays:r}){return{assign:W,sendTo:Je,raise:ge,log:bn,cancel:fe,stopChild:re,enqueueActions:wn,emit:wt,spawnChild:me,createStateConfig:o=>o,createAction:o=>o,createMachine:o=>or({...o,schemas:t},{actors:e,actions:n,guards:i,delays:r}),extend:o=>bt({schemas:t,actors:e,actions:{...n,...o.actions},guards:{...i,...o.guards},delays:{...r,...o.delays}})}}var Rn=new TextEncoder;function sr(t,e){let n=Array.from(t),i=Array.from(e),r=Math.min(n.length,i.length);for(let o=0;o<r;o+=1){let s=n[o]?.codePointAt(0),a=i[o]?.codePointAt(0);if(!(s===void 0||a===void 0||s===a))return s<a?-1:1}return n.length===i.length?0:n.length<i.length?-1:1}function $n(t){if(!t.isWellFormed())throw new TypeError("Canonical runtime strings must contain valid Unicode")}function $t(t){if(t===null)return"null";if(typeof t=="string"||typeof t=="boolean")return typeof t=="string"&&$n(t),JSON.stringify(t);if(typeof t=="number"){if(!Number.isSafeInteger(t)||Object.is(t,-0))throw new TypeError("Canonical runtime numbers must be safe integers");return String(t)}if(Array.isArray(t))return`[${t.map(e=>$t(e)).join(",")}]`;if(typeof t=="object")return`{${Object.entries(t).sort(([n],[i])=>sr(n,i)).map(([n,i])=>{if($n(n),i===void 0)throw new TypeError(`Canonical runtime object field ${n} is undefined`);return`${JSON.stringify(n)}:${$t(i)}`}).join(",")}}`;throw new TypeError(`Unsupported canonical runtime value type: ${typeof t}`)}function ar(t){return Array.from(new Uint8Array(t),e=>e.toString(16).padStart(2,"0")).join("")}function In(t){return $t(t)}async function ve(t){let e=In(t),n=await globalThis.crypto.subtle.digest("SHA-256",Rn.encode(e));return`sha256:${ar(n)}`}function ur(t){let e=t.replaceAll("-","");if(!/^[0-9a-f]{32}$/u.test(e))throw new TypeError(`Invalid UUID namespace: ${t}`);let n=new Uint8Array(16);for(let i=0;i<n.length;i+=1){let r=i*2;n[i]=Number.parseInt(e.slice(r,r+2),16)}return n}function cr(t){let e=Array.from(t,n=>n.toString(16).padStart(2,"0")).join("");return`${e.slice(0,8)}-${e.slice(8,12)}-${e.slice(12,16)}-${e.slice(16,20)}-${e.slice(20)}`}async function Sn(t,e){let n=ur(t),i=Rn.encode(e),r=new Uint8Array(n.length+i.length);r.set(n),r.set(i,n.length);let s=new Uint8Array(await globalThis.crypto.subtle.digest("SHA-1",r)).slice(0,16);return s[6]=(s[6]??0)&15|80,s[8]=(s[8]??0)&63|128,cr(s)}var Rt="0.2.0-spike",It="5.32.4",dr="1af0c23d-70d2-5fd5-aad8-3f1eafbb10a1",$=class extends Error{constructor(n,i){super(i);this.code=n;this.name="RuntimeCoreError"}code};function P(t,e,n){if(t===void 0)throw new $(e,n);return t}function K(t,e){return N(t.map(n=>n.id),e)}function N(t,e){let n=new Set,i=[];for(let r of t)n.has(r)&&i.push(`${e} contains duplicate id ${r}`),n.add(r);return i}function se(t,e,n){return t.type==="null"?n:t.type===e}function Ge(t,e){return t.type!=="entityRef"||t.schemaId===e}function Ye(t){switch(t.kind){case"eventEntityRef":return!0;case"entityField":return Ye(t.entityRef);case"literal":case"variable":case"formField":return!1}}function En(t){switch(t.kind){case"all":return t.items.some(En);case"compare":return Ye(t.left)||Ye(t.right);case"roleIs":case"formValid":return!1}}function _n(t){let e=[...N(t.pageIds,"pages"),...K(t.roles,"roles"),...K(t.variables,"variables"),...K(t.entitySchemas,"entitySchemas"),...K(t.forms,"forms"),...K(t.viewBindings,"viewBindings"),...N(t.viewBindings.map(o=>`${o.nodeId}:${o.target}`),"view binding node targets"),...K(t.rules,"rules"),...K(t.scenarios,"scenarios")],n=new Set(t.roles.map(o=>o.id)),i=new Set(t.pageIds),r=new Set(t.entitySchemas.map(o=>o.id));for(let o of t.variables)o.valueType==="entityRef"?o.entitySchemaId===null?e.push(`variable ${o.id} entityRef type requires an entity schema`):r.has(o.entitySchemaId)||e.push(`variable ${o.id} references unknown entity schema ${o.entitySchemaId}`):o.entitySchemaId!==null&&e.push(`variable ${o.id} non-entityRef type cannot declare an entity schema`),se(o.defaultValue,o.valueType,o.nullable)?Ge(o.defaultValue,o.entitySchemaId)||e.push(`variable ${o.id} default entity schema does not match its definition`):e.push(`variable ${o.id} default value does not match ${o.valueType}`);for(let o of t.scenarios){e.push(...N(o.initialVariables.map(s=>s.variableId),`scenario ${o.id} variables`),...N(o.entityFixtures.map(s=>s.schemaId),`scenario ${o.id} entity fixtures`)),n.has(o.actorRoleId)||e.push(`scenario ${o.id} references unknown role ${o.actorRoleId}`),i.has(o.startPageId)||e.push(`scenario ${o.id} references unknown page ${o.startPageId}`);for(let s of o.initialVariables){let a=t.variables.find(u=>u.id===s.variableId);a===void 0?e.push(`scenario ${o.id} references unknown variable ${s.variableId}`):se(s.value,a.valueType,a.nullable)?Ge(s.value,a.entitySchemaId)||e.push(`scenario ${o.id} variable ${s.variableId} entity schema does not match its definition`):e.push(`scenario ${o.id} variable ${s.variableId} does not match ${a.valueType}`)}for(let s of o.entityFixtures)r.has(s.schemaId)||e.push(`scenario ${o.id} references unknown schema ${s.schemaId}`)}for(let o of t.rules){o.effects.length===0&&e.push(`rule ${o.id} has no effects`);for(let s of[...o.effects,...o.guardFalseEffects]){if(s.kind!=="createEntity")continue;let a=t.variables.find(u=>u.id===s.resultVariableId);(a===void 0||a.valueType!=="entityRef"||a.entitySchemaId!==s.schemaId)&&e.push(`rule ${o.id} create-entity result variable does not match schema ${s.schemaId}`)}}for(let o of t.viewBindings)o.target==="tableRows"&&!r.has(o.schemaId)&&e.push(`view binding ${o.id} references unknown schema ${o.schemaId}`),(o.target==="textContent"&&Ye(o.value)||o.target==="visibility"&&En(o.predicate))&&e.push(`view binding ${o.id} cannot reference the current event entity`);for(let o of t.forms)e.push(...K(o.fields,`form ${o.id} fields`));for(let o of t.entitySchemas)e.push(...K(o.fields,`schema ${o.id} fields`));return t.roles.length===0&&e.push("runtime definition requires at least one role"),t.scenarios.length===0&&e.push("runtime definition requires at least one scenario"),e}function Tn(t,e){let n=[];e.runtimeCoreVersion!==Rt&&n.push(`runtime core version ${e.runtimeCoreVersion} does not match ${Rt}`),e.stateMachineKernelVersion!==It&&n.push(`state machine kernel version ${e.stateMachineKernelVersion} does not match ${It}`),e.sessionId.length===0&&n.push("runtime session id must not be empty"),e.sequenceNo<0&&n.push("runtime sequence must not be negative"),t.roles.some(r=>r.id===e.actorRoleId)||n.push(`runtime state references unknown role ${e.actorRoleId}`),t.pageIds.includes(e.currentPageId)||n.push(`runtime state references unknown current page ${e.currentPageId}`);for(let r of e.navigationStack)t.pageIds.includes(r)||n.push(`runtime navigation stack references unknown page ${r}`);let i=t.scenarios.find(r=>r.id===e.scenarioId);i===void 0?n.push(`runtime state references unknown scenario ${e.scenarioId}`):e.allowSimulatedRoleSwitch!==i.allowSimulatedRoleSwitch&&n.push(`runtime state role-switch policy does not match scenario ${e.scenarioId}`),n.push(...N(e.variableValues.map(r=>r.variableId),"runtime variable values"));for(let r of t.variables)e.variableValues.some(o=>o.variableId===r.id)||n.push(`runtime state is missing variable ${r.id}`);for(let r of e.variableValues){let o=t.variables.find(s=>s.id===r.variableId);o===void 0?n.push(`runtime state contains unknown variable ${r.variableId}`):se(r.value,o.valueType,o.nullable)?Ge(r.value,o.entitySchemaId)||n.push(`runtime variable ${r.variableId} entity schema does not match its definition`):n.push(`runtime variable ${r.variableId} does not match ${o.valueType}`)}n.push(...N(e.entitySets.map(r=>r.schemaId),"runtime entity sets"));for(let r of t.entitySchemas)e.entitySets.some(o=>o.schemaId===r.id)||n.push(`runtime state is missing entity set ${r.id}`);for(let r of e.entitySets){let o=t.entitySchemas.find(s=>s.id===r.schemaId);if(o===void 0){n.push(`runtime state contains unknown entity set ${r.schemaId}`);continue}n.push(...N(r.entities.map(s=>s.id),`runtime entity set ${r.schemaId}`));for(let s of r.entities){s.schemaId!==r.schemaId&&n.push(`runtime entity ${s.id} schema does not match set ${r.schemaId}`),n.push(...N(s.fields.map(a=>a.fieldId),`runtime entity ${s.id} fields`));for(let a of o.fields)s.fields.some(u=>u.fieldId===a.id)||n.push(`runtime entity ${s.id} is missing field ${a.id}`);for(let a of s.fields){let u=o.fields.find(d=>d.id===a.fieldId);u===void 0?n.push(`runtime entity ${s.id} contains unknown field ${a.fieldId}`):se(a.value,u.valueType,u.nullable)||n.push(`runtime entity ${s.id} field ${a.fieldId} does not match ${u.valueType}`)}}}n.push(...N(e.formStates.map(r=>r.formId),"runtime form states"));for(let r of t.forms)e.formStates.some(o=>o.formId===r.id)||n.push(`runtime state is missing form ${r.id}`);for(let r of e.formStates){let o=t.forms.find(s=>s.id===r.formId);if(o===void 0){n.push(`runtime state contains unknown form ${r.formId}`);continue}n.push(...N(r.values.map(s=>s.fieldId),`runtime form ${r.formId} values`));for(let s of o.fields)r.values.some(a=>a.fieldId===s.id)||n.push(`runtime form ${r.formId} is missing field ${s.id}`);for(let s of r.values){let a=o.fields.find(u=>u.id===s.fieldId);a===void 0?n.push(`runtime form ${r.formId} contains unknown field ${s.fieldId}`):s.value.type!==a.valueType&&n.push(`runtime form ${r.formId} field ${s.fieldId} does not match ${a.valueType}`)}for(let s of r.errors)o.fields.some(a=>a.id===s.fieldId)||n.push(`runtime form ${r.formId} error references unknown field ${s.fieldId}`)}return n.push(...N(e.notifications.map(r=>r.id),"runtime notifications")),n}function A(t){return{...t}}function Vn(t){return t.map(e=>({fieldId:e.fieldId,value:A(e.value)}))}function xt(t){return{id:t.id,schemaId:t.schemaId,fields:Vn(t.fields)}}function St(t){return{...t,navigationStack:[...t.navigationStack],variableValues:t.variableValues.map(e=>({variableId:e.variableId,value:A(e.value)})),entitySets:t.entitySets.map(e=>({schemaId:e.schemaId,entities:e.entities.map(xt)})),formStates:t.formStates.map(e=>({formId:e.formId,values:Vn(e.values),errors:e.errors.map(n=>({...n}))})),notifications:t.notifications.map(e=>({...e}))}}function Pn(t,e,n){let i=_n(t);if(i.length>0)throw new $("runtime_definition_invalid",i.join("; "));let r=P(t.scenarios.find(u=>u.id===e),"runtime_scenario_missing",`Unknown runtime scenario ${e}`),o=new Map(r.initialVariables.map(u=>[u.variableId,u.value])),s={runtimeStateSchemaVersion:1,sessionId:n,scenarioId:e,runtimeCoreVersion:Rt,stateMachineKernelVersion:It,sequenceNo:0,actorRoleId:r.actorRoleId,currentPageId:r.startPageId,navigationStack:[],variableValues:t.variables.map(u=>({variableId:u.id,value:A(o.get(u.id)??u.defaultValue)})),entitySets:t.entitySchemas.map(u=>{let d=r.entityFixtures.find(m=>m.schemaId===u.id);return{schemaId:u.id,entities:d===void 0?[]:d.entities.map(xt)}}),formStates:t.forms.map(u=>({formId:u.id,values:u.fields.map(d=>({fieldId:d.id,value:A(d.initialValue)})),errors:[]})),notifications:[],allowSimulatedRoleSwitch:r.allowSimulatedRoleSwitch},a=Tn(t,s);if(a.length>0)throw new $("runtime_state_invalid",a.join("; "));return s}function Ze(t,e){return P(t.formStates.find(n=>n.formId===e),"runtime_form_state_missing",`Runtime form state ${e} does not exist`)}function Ve(t,e){return P(t.find(n=>n.fieldId===e),"runtime_field_value_missing",`Runtime field value ${e} does not exist`).value}function lr(t,e){return P(t.variableValues.find(n=>n.variableId===e),"runtime_variable_value_missing",`Runtime variable ${e} does not exist`).value}function Xe(t,e){return P(t.entitySets.find(n=>n.schemaId===e),"runtime_entity_set_missing",`Runtime entity set ${e} does not exist`)}function fr(t,e,n){let i=Y(t,e,n);if(i.type!=="entityRef")throw new $("runtime_entity_ref_required","Expression did not resolve to entityRef");return i}function Y(t,e,n){switch(e.kind){case"literal":return A(e.value);case"variable":return A(lr(t,e.variableId));case"formField":return A(Ve(Ze(t,e.formId).values,e.fieldId));case"eventEntityRef":if(n.kind!=="tableRowActivated")throw new $("runtime_event_entity_ref_missing","Current runtime event has no entity reference");return A(n.entityRef);case"entityField":{let i=Y(t,e.entityRef,n);if(i.type==="null")return A(e.fallback);if(i.type!=="entityRef")throw new $("runtime_entity_ref_required","Entity field expression did not resolve to entityRef");let r=i,o=P(Xe(t,r.schemaId).entities.find(s=>s.id===r.entityId),"runtime_entity_missing",`Runtime entity ${r.entityId} does not exist`);return A(Ve(o.fields,e.fieldId))}}}function mr(t,e){if(t.type!==e.type)return!1;switch(t.type){case"null":return!0;case"boolean":return e.type==="boolean"&&t.value===e.value;case"integer":return e.type==="integer"&&t.value===e.value;case"string":return e.type==="string"&&t.value===e.value;case"enum":return e.type==="enum"&&t.value===e.value;case"entityRef":return e.type==="entityRef"&&t.schemaId===e.schemaId&&t.entityId===e.entityId}}function Nn(t,e,n){let i=P(t.forms.find(s=>s.id===n),"runtime_form_definition_missing",`Runtime form definition ${n} does not exist`),r=Ze(e,n),o=[];for(let s of i.fields){let a=Ve(r.values,s.id);if(s.valueType!==a.type){o.push({fieldId:s.id,code:"type_mismatch"});continue}s.required&&a.type==="string"&&a.value.trim().length===0&&o.push({fieldId:s.id,code:"required"}),s.required&&a.type==="integer"&&s.minInteger!==null&&a.value<s.minInteger&&o.push({fieldId:s.id,code:"min_integer"})}return o}function kt(t,e,n,i){switch(n.kind){case"all":return n.items.every(r=>kt(t,e,r,i));case"roleIs":return e.actorRoleId===n.roleId;case"formValid":return Nn(t,e,n.formId).length===0;case"compare":{let r=mr(Y(e,n.left,i),Y(e,n.right,i));return n.operator==="eq"?r:!r}}}function xn(t,e,n,i){let r=P(t.variables.find(a=>a.id===n),"runtime_variable_definition_missing",`Unknown variable definition ${n}`);if(!se(i,r.valueType,r.nullable))throw new $("runtime_variable_type_mismatch",`Variable ${n} requires ${r.valueType}`);if(!Ge(i,r.entitySchemaId))throw new $("runtime_variable_entity_schema_mismatch",`Variable ${n} requires entity schema ${r.entitySchemaId}`);let o=!1,s=e.variableValues.map(a=>a.variableId!==n?a:(o=!0,{variableId:n,value:A(i)}));if(!o)throw new $("runtime_variable_value_missing",`Unknown variable ${n}`);return{...e,variableValues:s}}function An(t,e,n){return{...t,formStates:t.formStates.map(i=>i.formId===e?n:i)}}function kn(t,e,n){return{...t,entitySets:t.entitySets.map(i=>i.schemaId===e?n:i)}}function pr(t,e){return P(t.find(n=>n.key===e),"runtime_entity_allocation_missing",`Runtime entity allocation ${e} does not exist`).entityId}function hr(t,e,n,i,r,o,s,a){switch(i.kind){case"setVariable":return{state:xn(t,e,i.variableId,Y(e,i.value,n)),stop:!1,outcome:"applied"};case"validateForm":{let u=Nn(t,e,i.formId),d=Ze(e,i.formId);return{state:An(e,i.formId,{...d,errors:u}),stop:u.length>0,outcome:u.length>0?"validation_failed":"applied"}}case"createEntity":{let u=pr(a,`${r}:${o}:${s}`),m=P(t.entitySchemas.find(f=>f.id===i.schemaId),"runtime_entity_schema_missing",`Runtime schema ${i.schemaId} does not exist`).fields.map(f=>{let p=P(i.values.find(y=>y.fieldId===f.id),"runtime_entity_field_assignment_missing",`Create effect is missing field ${f.id}`),h=Y(e,p.value,n);if(!se(h,f.valueType,f.nullable))throw new $("runtime_entity_field_type_mismatch",`Entity field ${f.id} value does not match ${f.valueType}`);return{fieldId:f.id,value:h}}),l=Xe(e,i.schemaId),c=kn(e,i.schemaId,{...l,entities:[...l.entities,{id:u,schemaId:i.schemaId,fields:m}]});return{state:xn(t,c,i.resultVariableId,{type:"entityRef",schemaId:i.schemaId,entityId:u}),stop:!1,outcome:"applied"}}case"updateEntity":{let u=fr(e,i.entityRef,n);if(u.schemaId!==i.schemaId)throw new $("runtime_entity_schema_mismatch",`Entity ref schema ${u.schemaId} does not match ${i.schemaId}`);let d=P(t.entitySchemas.find(f=>f.id===i.schemaId),"runtime_entity_schema_missing",`Runtime schema ${i.schemaId} does not exist`),m=Xe(e,i.schemaId),l=!1,c=m.entities.map(f=>{if(f.id!==u.entityId)return f;l=!0;let p=f.fields.map(h=>{let y=i.updates.find(ee=>ee.fieldId===h.fieldId);if(y===void 0)return h;let _=P(d.fields.find(ee=>ee.id===y.fieldId),"runtime_entity_field_missing",`Runtime field ${y.fieldId} does not exist`),C=Y(e,y.value,n);if(!se(C,_.valueType,_.nullable))throw new $("runtime_entity_field_type_mismatch",`Entity field ${_.id} value does not match ${_.valueType}`);return{fieldId:h.fieldId,value:C}});return{...f,fields:p}});if(!l)throw new $("runtime_entity_missing",`Runtime entity ${u.entityId} does not exist`);return{state:kn(e,i.schemaId,{...m,entities:c}),stop:!1,outcome:"applied"}}case"navigate":{if(!t.pageIds.includes(i.targetPageId))throw new $("runtime_page_missing",`Runtime page ${i.targetPageId} does not exist`);return{state:{...e,currentPageId:i.targetPageId,navigationStack:e.currentPageId===i.targetPageId?e.navigationStack:[...e.navigationStack,e.currentPageId]},stop:!1,outcome:"applied"}}case"notify":return{state:{...e,notifications:[...e.notifications,{id:`${e.sessionId}:${e.sequenceNo+1}:${r}:${s}`,level:i.level,message:i.message}]},stop:!1,outcome:"applied"}}}function Fn(t){switch(t.kind){case"nodeActivated":return{nodeId:t.nodeId,event:t.event};case"tableRowActivated":return{nodeId:t.nodeId,event:"rowActivated"};case"fieldValueCommitted":case"switchSimulatedRole":return null}}function Dn(t,e){let n=Fn(e);if(n===null)return null;let i=t.rules.filter(r=>r.enabled&&r.trigger.kind==="nodeEvent"&&r.trigger.nodeId===n.nodeId&&r.trigger.event===n.event);if(i.length>1)throw new $("runtime_rule_ambiguous",`Multiple runtime rules match node ${n.nodeId} event ${n.event}`);return i[0]??null}function gr(t,e,n){if(n.kind!=="tableRowActivated")return;let r=Qe(t,e).nodes.find(s=>s.nodeId===n.nodeId)?.properties.find(s=>s.target==="tableRows");if(r?.target!=="tableRows")throw new $("runtime_table_binding_missing",`Runtime table ${n.nodeId} has no rows binding`);if(!r.rows.some(s=>s.id===n.entityRef.entityId&&s.schemaId===n.entityRef.schemaId))throw new $("runtime_table_entity_not_visible",`Runtime entity ${n.entityRef.entityId} is not visible in table ${n.nodeId}`)}function yr(t,e,n){if(n.kind!=="fieldValueCommitted")return e;let i=P(t.forms.find(s=>s.id===n.formId),"runtime_form_definition_missing",`Runtime form definition ${n.formId} does not exist`),r=P(i.fields.find(s=>s.id===n.fieldId),"runtime_form_field_missing",`Runtime form field ${n.fieldId} does not exist`);if(n.value.type!==r.valueType)throw new $("runtime_form_field_type_mismatch",`Runtime form field ${n.fieldId} requires ${r.valueType}`);let o=Ze(e,n.formId);return An(e,n.formId,{...o,values:o.values.map(s=>s.fieldId===n.fieldId?{...s,value:A(n.value)}:s),errors:o.errors.filter(s=>s.fieldId!==n.fieldId)})}function vr(t,e,n){if(n.kind!=="switchSimulatedRole")return e;if(!e.allowSimulatedRoleSwitch)throw new $("runtime_role_switch_forbidden","Runtime scenario does not allow simulated role switching");if(!t.roles.some(i=>i.id===n.roleId))throw new $("runtime_role_missing",`Runtime role ${n.roleId} does not exist`);return{...e,actorRoleId:n.roleId}}function wr(t,e,n,i,r,o,s,a){let u=e,d="applied";for(let[m,l]of o.entries()){let c=St(u),f=hr(t,u,n,l,i,r,m,s);if(u=f.state,d=f.outcome,a.push({eventIndex:i,effectIndex:m,effectKind:l.kind,beforeState:c,afterState:St(u)}),f.stop)return{state:u,stop:!0,outcome:d}}return{state:u,stop:!1,outcome:d}}function br(t,e,n,i){let r=St(e),o="applied",s=[],a=[];for(let[u,d]of n.events.entries()){r=yr(t,r,d),r=vr(t,r,d);let m=Fn(d),l=Dn(t,d);if(m===null)continue;if(l===null)throw new $("runtime_rule_missing",`No runtime rule matches node ${m.nodeId}`);gr(t,r,d),s.push(l.id);let c=l.guard===null||kt(t,r,l.guard,d),f=c?"effects":"guardFalseEffects",p=l[f];c||(o="guard_false");let h=wr(t,r,d,u,f,p,i,a);if(r=h.state,h.outcome==="validation_failed"&&(o="validation_failed"),h.stop)break}return{state:{...r,sequenceNo:e.sequenceNo+1},outcome:o,matchedRuleIds:s,effectTraces:a}}var $r=bt({types:{context:{},events:{},input:{}},actions:{applyRuntimeEventBatch:W(({context:t,event:e})=>{let n=br(t.definition,t.state,e.batch,e.allocations);return{...t,state:n.state,reduction:n}})}}).createMachine({id:"prototype-runtime",initial:"ready",context:({input:t})=>({...t,reduction:null}),states:{ready:{on:{"runtime.eventBatch":{actions:"applyRuntimeEventBatch"}}}}});async function Rr(t,e,n){let i=[];for(let[r,o]of n.events.entries()){let s=Dn(t,o);if(s===null)continue;let a=["effects","guardFalseEffects"];for(let u of a)for(let[d,m]of s[u].entries()){if(m.kind!=="createEntity")continue;let l=`${r}:${u}:${d}`,c=`${e.sessionId}:${e.sequenceNo+1}:${l}`;i.push(Sn(dr,c).then(f=>({key:l,entityId:f})))}}return Promise.all(i)}function Ir(t,e){if(t.type!==e.type)return t.type<e.type?-1:1;switch(t.type){case"null":return 0;case"boolean":return e.type!=="boolean"||t.value===e.value?0:t.value?1:-1;case"integer":return e.type!=="integer"||t.value===e.value?0:t.value<e.value?-1:1;case"string":return e.type!=="string"||t.value===e.value?0:t.value<e.value?-1:1;case"enum":return e.type!=="enum"||t.value===e.value?0:t.value<e.value?-1:1;case"entityRef":{if(e.type!=="entityRef")return 0;let n=`${t.schemaId}:${t.entityId}`,i=`${e.schemaId}:${e.entityId}`;return n===i?0:n<i?-1:1}}}function Qe(t,e){let n=new Map,i={kind:"switchSimulatedRole",roleId:e.actorRoleId};for(let o of t.viewBindings){let s=n.get(o.nodeId)??[],a;switch(o.target){case"textContent":a={target:"textContent",value:Y(e,o.value,i)};break;case"visibility":a={target:"visibility",value:{type:"boolean",value:kt(t,e,o.predicate,i)}};break;case"tableRows":{let d=Xe(e,o.schemaId).entities.map(xt),m=o.sortFieldId;m!==null&&d.sort((l,c)=>{let f=Ir(Ve(l.fields,m),Ve(c.fields,m));return o.sortDirection==="asc"?f:-f}),a={target:"tableRows",rows:d};break}}n.set(o.nodeId,[...s,a])}return{nodes:Array.from(n,([o,s])=>({nodeId:o,properties:[...s].sort((a,u)=>a.target===u.target?0:a.target<u.target?-1:1)})).sort((o,s)=>o.nodeId===s.nodeId?0:o.nodeId<s.nodeId?-1:1)}}async function Mn(t,e,n){let i=_n(t);if(i.length>0)throw new $("runtime_definition_invalid",i.join("; "));let r=Tn(t,e);if(r.length>0)throw new $("runtime_state_invalid",r.join("; "));if(n.expectedSequenceNo!==e.sequenceNo)throw new $("runtime_sequence_conflict",`Expected runtime sequence ${n.expectedSequenceNo}, current is ${e.sequenceNo}`);if(n.events.length===0||n.events.length>20)throw new $("runtime_event_batch_size_invalid","Runtime event batch must contain between 1 and 20 events");let o=await ve(e),s=await Rr(t,e,n),a=q($r,{input:{definition:t,state:e}}),u,d=!1,m=a.subscribe({error:y=>{d=!0,u=y}});a.start(),a.send({type:"runtime.eventBatch",batch:n,allocations:s});let l=a.getSnapshot().context.reduction;if(m.unsubscribe(),a.stop(),d)throw u;if(l===null)throw new $("runtime_transition_missing","XState runtime transition produced no reduction");let c=Qe(t,l.state),[f,p,h]=await Promise.all([ve(l.state),ve(c),Promise.all(l.effectTraces.map(async y=>({eventIndex:y.eventIndex,effectIndex:y.effectIndex,effectKind:y.effectKind,beforeStateHash:await ve(y.beforeState),afterStateHash:await ve(y.afterState)})))]);return{state:l.state,viewModel:c,report:{clientEventId:n.clientEventId,baseSequenceNo:e.sequenceNo,resultSequenceNo:l.state.sequenceNo,outcome:l.outcome,matchedRuleIds:l.matchedRuleIds,baseStateHash:o,resultStateHash:f,resultViewModelHash:p,effects:h}}}function X(t){return t.type==="Stack"||t.type==="Grid"||t.type==="Form"||t.type==="Freeform"}var Z=class extends Error{constructor(n,i){super(i);this.code=n;this.name="PrototypeRendererError"}code};function Cn(t,e){if(t.type==="Input"&&e.push(t),X(t))for(let n of t.children)Cn(n,e)}function On(t,e){if(t.type==="Form"&&e.push(t),X(t))for(let n of t.children)On(n,e)}function Bn(t,e=!0){let n=[];for(let r of t.pages)On(r.root,n);let i=[];for(let r of n){let o=t.runtime.forms.find(u=>u.id===r.formDefinitionId);if(o===void 0)throw new Z("renderer_form_definition_missing",`form node ${r.id} references an unknown runtime form`);let s=[];for(let u of r.children)Cn(u,s);let a=new Set;for(let u of s){if(u.formDefinitionId===null&&u.formFieldId===null)continue;if(u.formDefinitionId!==o.id||u.formFieldId===null)throw new Z("renderer_form_binding_invalid",`input node ${u.id} does not belong to runtime form ${o.id}`);let d=o.fields.find(l=>l.id===u.formFieldId);if(d===void 0)throw new Z("renderer_form_field_missing",`input node ${u.id} references an unknown runtime field`);if(a.has(d.id))throw new Z("renderer_form_binding_duplicate",`runtime field ${d.id} is bound more than once in form node ${r.id}`);if(!(d.valueType==="integer"&&u.inputType==="number"||d.valueType==="string"&&u.inputType!=="number"))throw new Z("renderer_form_binding_type_mismatch",`input node ${u.id} does not match runtime field ${d.id}`);a.add(d.id),i.push({nodeId:u.id,formId:o.id,fieldId:d.id,valueType:d.valueType})}if(e&&a.size!==o.fields.length)throw new Z("renderer_form_binding_incomplete",`form node ${r.id} must bind every runtime field exactly once`)}return i}var L=class extends Error{constructor(e){super(e),this.name="RuntimeStateCodecError"}};function Sr(t){return typeof t=="object"&&t!==null&&!Array.isArray(t)}function Pe(t,e){if(!Sr(t))throw new L(`${e} must be an object`);return t}function j(t,e,n){let i=new Set(e);for(let r of Object.keys(t))if(!i.has(r))throw new L(`${n} contains unknown field ${r}`);for(let r of e)if(!Object.hasOwn(t,r))throw new L(`${n} is missing field ${r}`)}function U(t,e){if(typeof t!="string")throw new L(`${e} must be a string`);return t}function xr(t,e){if(typeof t!="boolean")throw new L(`${e} must be a boolean`);return t}function kr(t,e){if(typeof t!="number"||!Number.isSafeInteger(t)||Object.is(t,-0))throw new L(`${e} must be a safe integer`);return t}function qn(t,e){if(!Array.isArray(t))throw new L(`${e} must be an array`);return t}function Er(t,e,n){if(typeof t=="string"){for(let i of e)if(i===t)return i}throw new L(`${n} has an unsupported value`)}function ae(t,e){let n=Pe(t,e);switch(Er(n.type,["null","boolean","integer","string","enum","entityRef"],`${e}.type`)){case"null":return j(n,["type"],e),{type:"null"};case"boolean":return j(n,["type","value"],e),{type:"boolean",value:xr(n.value,`${e}.value`)};case"integer":return j(n,["type","value"],e),{type:"integer",value:kr(n.value,`${e}.value`)};case"string":return j(n,["type","value"],e),{type:"string",value:U(n.value,`${e}.value`)};case"enum":return j(n,["type","value"],e),{type:"enum",value:U(n.value,`${e}.value`)};case"entityRef":return j(n,["type","schemaId","entityId"],e),{type:"entityRef",schemaId:U(n.schemaId,`${e}.schemaId`),entityId:U(n.entityId,`${e}.entityId`)}}}function _r(t,e){let n=Pe(t,e);return j(n,["fieldId","value"],e),{fieldId:U(n.fieldId,`${e}.fieldId`),value:ae(n.value,`${e}.value`)}}function jn(t,e){let n=Pe(t,e);return j(n,["variableId","value"],e),{variableId:U(n.variableId,`${e}.variableId`),value:ae(n.value,`${e}.value`)}}function Tr(t,e){let n=Pe(t,e);return j(n,["id","schemaId","fields"],e),{id:U(n.id,`${e}.id`),schemaId:U(n.schemaId,`${e}.schemaId`),fields:qn(n.fields,`${e}.fields`).map((i,r)=>_r(i,`${e}.fields[${r}]`))}}function Ln(t,e){let n=Pe(t,e);return j(n,["schemaId","entities"],e),{schemaId:U(n.schemaId,`${e}.schemaId`),entities:qn(n.entities,`${e}.entities`).map((i,r)=>Tr(i,`${e}.entities[${r}]`))}}var Vr=32,S=class extends Error{constructor(e){super(e),this.name="RuntimeInputCodecError"}};function Pr(t){return typeof t=="object"&&t!==null&&!Array.isArray(t)}function E(t,e){if(!Pr(t))throw new S(`${e} must be an object`);return t}function w(t,e,n){let i=new Set(e);for(let r of Object.keys(t))if(!i.has(r))throw new S(`${n} contains unknown field ${r}`);for(let r of e)if(!Object.hasOwn(t,r))throw new S(`${n} is missing field ${r}`)}function Et(t,e){if(typeof t!="string")throw new S(`${e} must be a string`);return t}function v(t,e){let n=Et(t,e);if(n.length===0)throw new S(`${e} must not be empty`);return n}function Ae(t,e){if(typeof t!="boolean")throw new S(`${e} must be a boolean`);return t}function Un(t,e){if(typeof t!="number"||!Number.isSafeInteger(t)||Object.is(t,-0))throw new S(`${e} must be a safe integer`);return t}function k(t,e){if(!Array.isArray(t))throw new S(`${e} must be an array`);return t}function F(t,e,n){if(typeof t=="string"){for(let i of e)if(i===t)return i}throw new S(`${n} has an unsupported value`)}function Nr(t,e){return t===null?null:Un(t,e)}function zn(t,e){let n=Un(t,e);if(n<-32768||n>32768)throw new S(`${e} must be between ${-32768} and ${32768}`);return n}function Jn(t,e){if(t>Vr)throw new S(`${e} exceeds the maximum expression depth`)}function Ar(t,e){let n=E(t,e);return w(n,["id","key","label"],e),{id:v(n.id,`${e}.id`),key:v(n.key,`${e}.key`),label:Et(n.label,`${e}.label`)}}function Fr(t,e){let n=E(t,e);return w(n,["id","key","valueType","nullable","entitySchemaId","defaultValue"],e),{id:v(n.id,`${e}.id`),key:v(n.key,`${e}.key`),valueType:F(n.valueType,["null","boolean","integer","string","enum","entityRef"],`${e}.valueType`),nullable:Ae(n.nullable,`${e}.nullable`),entitySchemaId:n.entitySchemaId===null?null:v(n.entitySchemaId,`${e}.entitySchemaId`),defaultValue:ae(n.defaultValue,`${e}.defaultValue`)}}function Dr(t,e){let n=E(t,e);return w(n,["id","key","valueType","nullable"],e),{id:v(n.id,`${e}.id`),key:v(n.key,`${e}.key`),valueType:F(n.valueType,["null","boolean","integer","string","enum","entityRef"],`${e}.valueType`),nullable:Ae(n.nullable,`${e}.nullable`)}}function Mr(t,e){let n=E(t,e);return w(n,["id","key","fields"],e),{id:v(n.id,`${e}.id`),key:v(n.key,`${e}.key`),fields:k(n.fields,`${e}.fields`).map((i,r)=>Dr(i,`${e}.fields[${r}]`))}}function Cr(t,e){let n=E(t,e);w(n,["id","key","valueType","initialValue","required","minInteger"],e);let i=F(n.valueType,["string","integer"],`${e}.valueType`),r=ae(n.initialValue,`${e}.initialValue`),o;if(i==="string"){if(r.type!=="string")throw new S(`${e}.initialValue must be a string runtime value`);o=r}else{if(r.type!=="integer")throw new S(`${e}.initialValue must be an integer runtime value`);o=r}return{id:v(n.id,`${e}.id`),key:v(n.key,`${e}.key`),valueType:i,initialValue:o,required:Ae(n.required,`${e}.required`),minInteger:Nr(n.minInteger,`${e}.minInteger`)}}function Or(t,e){let n=E(t,e);return w(n,["id","key","fields"],e),{id:v(n.id,`${e}.id`),key:v(n.key,`${e}.key`),fields:k(n.fields,`${e}.fields`).map((i,r)=>Cr(i,`${e}.fields[${r}]`))}}function Gn(t,e){let n=E(t,e),i=F(n.kind,["variable","eventEntityRef"],`${e}.kind`);return i==="variable"?(w(n,["kind","variableId"],e),{kind:i,variableId:v(n.variableId,`${e}.variableId`)}):(w(n,["kind"],e),{kind:i})}function Ne(t,e,n=0){Jn(n,e);let i=E(t,e),r=F(i.kind,["literal","variable","formField","eventEntityRef","entityField"],`${e}.kind`);switch(r){case"literal":return w(i,["kind","value"],e),{kind:r,value:ae(i.value,`${e}.value`)};case"variable":return w(i,["kind","variableId"],e),{kind:r,variableId:v(i.variableId,`${e}.variableId`)};case"formField":return w(i,["kind","formId","fieldId"],e),{kind:r,formId:v(i.formId,`${e}.formId`),fieldId:v(i.fieldId,`${e}.fieldId`)};case"eventEntityRef":return w(i,["kind"],e),{kind:r};case"entityField":return w(i,["kind","entityRef","fieldId","fallback"],e),{kind:r,entityRef:Gn(i.entityRef,`${e}.entityRef`),fieldId:v(i.fieldId,`${e}.fieldId`),fallback:ae(i.fallback,`${e}.fallback`)}}}function _t(t,e,n=0){Jn(n,e);let i=E(t,e),r=F(i.kind,["all","roleIs","formValid","compare"],`${e}.kind`);switch(r){case"all":return w(i,["kind","items"],e),{kind:r,items:k(i.items,`${e}.items`).map((o,s)=>_t(o,`${e}.items[${s}]`,n+1))};case"roleIs":return w(i,["kind","roleId"],e),{kind:r,roleId:v(i.roleId,`${e}.roleId`)};case"formValid":return w(i,["kind","formId"],e),{kind:r,formId:v(i.formId,`${e}.formId`)};case"compare":return w(i,["kind","operator","left","right"],e),{kind:r,operator:F(i.operator,["eq","ne"],`${e}.operator`),left:Ne(i.left,`${e}.left`,n+1),right:Ne(i.right,`${e}.right`,n+1)}}}function Wn(t,e){let n=E(t,e);return w(n,["fieldId","value"],e),{fieldId:v(n.fieldId,`${e}.fieldId`),value:Ne(n.value,`${e}.value`)}}function Kn(t,e){let n=E(t,e),i=F(n.kind,["setVariable","validateForm","createEntity","updateEntity","navigate","notify"],`${e}.kind`);switch(i){case"setVariable":return w(n,["kind","variableId","value"],e),{kind:i,variableId:v(n.variableId,`${e}.variableId`),value:Ne(n.value,`${e}.value`)};case"validateForm":return w(n,["kind","formId"],e),{kind:i,formId:v(n.formId,`${e}.formId`)};case"createEntity":return w(n,["kind","schemaId","resultVariableId","values"],e),{kind:i,schemaId:v(n.schemaId,`${e}.schemaId`),resultVariableId:v(n.resultVariableId,`${e}.resultVariableId`),values:k(n.values,`${e}.values`).map((r,o)=>Wn(r,`${e}.values[${o}]`))};case"updateEntity":return w(n,["kind","schemaId","entityRef","updates"],e),{kind:i,schemaId:v(n.schemaId,`${e}.schemaId`),entityRef:Gn(n.entityRef,`${e}.entityRef`),updates:k(n.updates,`${e}.updates`).map((r,o)=>Wn(r,`${e}.updates[${o}]`))};case"navigate":return w(n,["kind","targetPageId"],e),{kind:i,targetPageId:v(n.targetPageId,`${e}.targetPageId`)};case"notify":return w(n,["kind","level","message"],e),{kind:i,level:F(n.level,["info","success","warning","error"],`${e}.level`),message:Et(n.message,`${e}.message`)}}}function Br(t,e){let n=E(t,e);w(n,["id","key","enabled","trigger","guard","effects","guardFalseEffects"],e);let i=E(n.trigger,`${e}.trigger`);if(w(i,["kind","nodeId","event"],`${e}.trigger`),i.kind!=="nodeEvent")throw new S(`${e}.trigger.kind must equal nodeEvent`);return{id:v(n.id,`${e}.id`),key:v(n.key,`${e}.key`),enabled:Ae(n.enabled,`${e}.enabled`),trigger:{kind:"nodeEvent",nodeId:v(i.nodeId,`${e}.trigger.nodeId`),event:F(i.event,["click","submit","rowActivated"],`${e}.trigger.event`)},guard:n.guard===null?null:_t(n.guard,`${e}.guard`),effects:k(n.effects,`${e}.effects`).map((r,o)=>Kn(r,`${e}.effects[${o}]`)),guardFalseEffects:k(n.guardFalseEffects,`${e}.guardFalseEffects`).map((r,o)=>Kn(r,`${e}.guardFalseEffects[${o}]`))}}function qr(t,e){let n=E(t,e),i=F(n.target,["textContent","visibility","tableRows"],`${e}.target`);return i==="textContent"?(w(n,["id","nodeId","target","value"],e),{id:v(n.id,`${e}.id`),nodeId:v(n.nodeId,`${e}.nodeId`),target:i,value:Ne(n.value,`${e}.value`)}):i==="visibility"?(w(n,["id","nodeId","target","predicate"],e),{id:v(n.id,`${e}.id`),nodeId:v(n.nodeId,`${e}.nodeId`),target:i,predicate:_t(n.predicate,`${e}.predicate`)}):(w(n,["id","nodeId","target","schemaId","sortFieldId","sortDirection"],e),{id:v(n.id,`${e}.id`),nodeId:v(n.nodeId,`${e}.nodeId`),target:i,schemaId:v(n.schemaId,`${e}.schemaId`),sortFieldId:n.sortFieldId===null?null:v(n.sortFieldId,`${e}.sortFieldId`),sortDirection:F(n.sortDirection,["asc","desc"],`${e}.sortDirection`)})}function jr(t,e){let n=E(t,e);return w(n,["id","key","actorRoleId","startPageId","initialVariables","entityFixtures","allowSimulatedRoleSwitch"],e),{id:v(n.id,`${e}.id`),key:v(n.key,`${e}.key`),actorRoleId:v(n.actorRoleId,`${e}.actorRoleId`),startPageId:v(n.startPageId,`${e}.startPageId`),initialVariables:k(n.initialVariables,`${e}.initialVariables`).map((i,r)=>jn(i,`${e}.initialVariables[${r}]`)),entityFixtures:k(n.entityFixtures,`${e}.entityFixtures`).map((i,r)=>Ln(i,`${e}.entityFixtures[${r}]`)),allowSimulatedRoleSwitch:Ae(n.allowSimulatedRoleSwitch,`${e}.allowSimulatedRoleSwitch`)}}function Lr(t,e){let n=E(t,e);w(n,["nodes"],e);let i=k(n.nodes,`${e}.nodes`);if(i.length>300)throw new S(`${e}.nodes exceeds the maximum length of ${300}`);let r=i.map((s,a)=>{let u=`${e}.nodes[${a}]`,d=E(s,u);return w(d,["nodeId","x","y"],u),{nodeId:v(d.nodeId,`${u}.nodeId`),x:zn(d.x,`${u}.x`),y:zn(d.y,`${u}.y`)}}),o=new Set;for(let s of r){if(o.has(s.nodeId))throw new S(`${e}.nodes contains duplicate nodeId ${s.nodeId}`);o.add(s.nodeId)}for(let s=1;s<r.length;s+=1){let a=r[s-1],u=r[s];if(a!==void 0&&u!==void 0&&u.nodeId<a.nodeId)throw new S(`${e}.nodes must use canonical nodeId order`)}return{nodes:r}}function Yn(t){let e=E(t,"runtimeDefinition"),n=Object.hasOwn(e,"flowLayout");if(w(e,["runtimeSchemaVersion","pageIds","roles","variables","entitySchemas","forms","viewBindings","rules","scenarios",...n?["flowLayout"]:[]],"runtimeDefinition"),e.runtimeSchemaVersion!==1)throw new S("runtimeDefinition.runtimeSchemaVersion must equal 1");return{runtimeSchemaVersion:1,pageIds:k(e.pageIds,"runtimeDefinition.pageIds").map((i,r)=>v(i,`runtimeDefinition.pageIds[${r}]`)),roles:k(e.roles,"runtimeDefinition.roles").map((i,r)=>Ar(i,`runtimeDefinition.roles[${r}]`)),variables:k(e.variables,"runtimeDefinition.variables").map((i,r)=>Fr(i,`runtimeDefinition.variables[${r}]`)),entitySchemas:k(e.entitySchemas,"runtimeDefinition.entitySchemas").map((i,r)=>Mr(i,`runtimeDefinition.entitySchemas[${r}]`)),forms:k(e.forms,"runtimeDefinition.forms").map((i,r)=>Or(i,`runtimeDefinition.forms[${r}]`)),viewBindings:k(e.viewBindings,"runtimeDefinition.viewBindings").map((i,r)=>qr(i,`runtimeDefinition.viewBindings[${r}]`)),rules:k(e.rules,"runtimeDefinition.rules").map((i,r)=>Br(i,`runtimeDefinition.rules[${r}]`)),scenarios:k(e.scenarios,"runtimeDefinition.scenarios").map((i,r)=>jr(i,`runtimeDefinition.scenarios[${r}]`)),...n?{flowLayout:Lr(e.flowLayout,"runtimeDefinition.flowLayout")}:{}}}var g=class extends Error{constructor(e){super(e),this.name="RendererDocumentCodecError"}};function Hr(t){return typeof t=="object"&&t!==null&&!Array.isArray(t)}function b(t,e){if(!Hr(t))throw new g(`${e} must be an object`);return t}function I(t,e,n,i=[]){let r=new Set([...e,...i]);for(let o of Object.keys(t))if(!r.has(o))throw new g(`${n} contains unknown field ${o}`);for(let o of e)if(!Object.hasOwn(t,o))throw new g(`${n} is missing field ${o}`)}function Fe(t,e){let n=M(t,e);if(!/^(?:0|[1-9][0-9]*)(?:\\.[0-9]{1,4})?$/u.test(n))throw new g(`${e} must be a canonical non-negative decimal`);let i=Number(n);if(i>4096)throw new g(`${e} must not exceed 4096`);return i}function Xn(t,e){let n=Fe(t,e);if(n<=0)throw new g(`${e} must be positive`);return n}function M(t,e){if(typeof t!="string")throw new g(`${e} must be a string`);return t}function ue(t,e){let n=M(t,e);if(n.length===0)throw new g(`${e} must not be empty`);return n}function we(t,e,n){let i=ue(t,n);if(i.length>e)throw new g(`${n} must contain at most ${e} characters`);return i}function De(t,e){if(typeof t!="boolean")throw new g(`${e} must be a boolean`);return t}function zr(t,e){if(typeof t!="number"||!Number.isSafeInteger(t)||Object.is(t,-0))throw new g(`${e} must be a safe integer`);return t}function T(t,e,n,i){let r=zr(t,i);if(r<e||r>n)throw new g(`${i} must be between ${e} and ${n}`);return r}function be(t,e){if(!Array.isArray(t))throw new g(`${e} must be an array`);return t}function Q(t,e,n,i){let r=be(t,i);if(r.length<e||r.length>n)throw new g(`${i} must contain between ${e} and ${n} items`);return r}function R(t,e,n){if(typeof t=="string"&&e.includes(t))return t;throw new g(`${n} has an unsupported value`)}function H(t,e){let n=M(t,e);if(!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u.test(n))throw new g(`${e} must be a canonical UUID`);return n}function x(t,e,n){let i=H(t,e);if(n.has(i))throw new g(`${e} is duplicated`);return n.add(i),i}function D(t,e){let n=M(t,e);if(!/^[a-z][a-z0-9-]{0,63}$/u.test(n))throw new g(`${e} must be a technical key`);return n}function Me(t,e){let n=b(t,e);I(n,["unit","value"],e);let i=R(n.unit,["px","percent","rem","auto"],`${e}.unit`);if(i==="auto"){if(n.value!==null)throw new g(`${e}.value must be null for auto length`);return}let r=M(n.value,`${e}.value`);if(!/^(?:0|[1-9][0-9]*)(?:\\.[0-9]{1,4})?$/u.test(r))throw new g(`${e}.value must be a canonical decimal`);let o=Number(r);if(i==="percent"&&o>100)throw new g(`${e}.value must not exceed 100 for percent length`);if(i==="px"&&o>4096)throw new g(`${e}.value must not exceed 4096 for px length`);if(i==="rem"&&o>256)throw new g(`${e}.value must not exceed 256 for rem length`)}function Nt(t,e){let n=b(t,e);I(n,["x","y"],e);for(let i of["x","y"])Fe(n[i],`${e}.${i}`)}function Wr(t,e,n,i,r,o){(t===void 0?[]:Q(t,0,8,e)).forEach((a,u)=>{let d=`${e}[${u}]`,m=b(a,d);if(I(m,["id","version","type","visible","snapEnabled","origin","params"],d),x(m.id,`${d}.id`,r),m.version!==1)throw new g(`${d}.version must equal 1`);let l=R(m.type,["square","columns","rows"],`${d}.type`);De(m.visible,`${d}.visible`),De(m.snapEnabled,`${d}.snapEnabled`),Nt(m.origin,`${d}.origin`);let c=b(m.origin,`${d}.origin`),f=Number(c.x),p=Number(c.y);if(f>=n||p>=i)throw new g(`${d}.origin must remain inside its Freeform`);let h=b(m.params,`${d}.params`),y=()=>{let Ce=D(h.colorTokenKey,`${d}.params.colorTokenKey`);if(!o.has(Ce))throw new g(`${d}.params.colorTokenKey references an unknown color token`);if(Fe(h.opacity,`${d}.params.opacity`)>1)throw new g(`${d}.params.opacity must be between 0 and 1`)};if(l==="square"){I(h,["size","colorTokenKey","opacity"],`${d}.params`);let Ce=Xn(h.size,`${d}.params.size`);if(f+Ce>n||p+Ce>i)throw new g(`${d} does not fit inside its Freeform`);y();return}I(h,["count","itemSize","gutter","margin","alignment","colorTokenKey","opacity"],`${d}.params`);let _=T(h.count,1,24,`${d}.params.count`),C=Fe(h.gutter,`${d}.params.gutter`),ee=Fe(h.margin,`${d}.params.margin`),ii=R(h.alignment,["stretch","start","center","end"],`${d}.params.alignment`),nt=h.itemSize===null?null:Xn(h.itemSize,`${d}.params.itemSize`);if(ii==="stretch"!=(nt===null))throw new g(`${d}.params.itemSize must be null only for stretch alignment`);let ri=l==="columns"?n-f:i-p,oi=ee*2+C*(_-1),Mt=ri-oi;if(Mt<=0||nt!==null&&nt*_>Mt)throw new g(`${d} does not fit inside its Freeform`);y()})}function Kr(t,e,n=!1){let i=b(t,e),r=new Set(["width","minWidth","maxWidth","height","minHeight","maxHeight","grow","shrink","alignSelf",...n?["position"]:[]]);for(let o of Object.keys(i))if(!r.has(o))throw new g(`${e} contains unknown field ${o}`);if(Object.keys(i).length===0)throw new g(`${e} must contain an update`);for(let o of["width","height"])Object.hasOwn(i,o)&&Me(i[o],`${e}.${o}`);for(let o of["minWidth","maxWidth","minHeight","maxHeight"])Object.hasOwn(i,o)&&i[o]!==null&&Me(i[o],`${e}.${o}`);for(let o of["grow","shrink"])Object.hasOwn(i,o)&&T(i[o],0,12,`${e}.${o}`);Object.hasOwn(i,"alignSelf")&&R(i.alignSelf,["auto","start","center","end","stretch"],`${e}.alignSelf`),Object.hasOwn(i,"position")&&i.position!==null&&Nt(i.position,`${e}.position`)}function Ur(t,e){let n=b(t,e),i=["width","minWidth","maxWidth","height","minHeight","maxHeight","grow","shrink","alignSelf"],r=[...i,"position"];for(let o of Object.keys(n))if(!r.includes(o))throw new g(`${e} contains unknown field ${o}`);for(let o of i)if(!Object.hasOwn(n,o))throw new g(`${e} is missing field ${o}`);Me(n.width,`${e}.width`),Me(n.height,`${e}.height`);for(let o of["minWidth","maxWidth","minHeight","maxHeight"])n[o]!==null&&Me(n[o],`${e}.${o}`);T(n.grow,0,12,`${e}.grow`),T(n.shrink,0,12,`${e}.shrink`),R(n.alignSelf,["auto","start","center","end","stretch"],`${e}.alignSelf`),Object.hasOwn(n,"position")&&Nt(n.position,`${e}.position`)}function Tt(t,e){let n=b(t,e);I(n,["top","right","bottom","left"],e);for(let i of["top","right","bottom","left"])T(n[i],0,256,`${e}.${i}`)}function Jr(t,e){H(t.id,`${e}.id`),we(t.name,80,`${e}.name`),R(t.visibility,["visible","hidden"],`${e}.visibility`),Ur(t.layoutItem,`${e}.layoutItem`);let n=new Set,i={sm:0,md:1,lg:2},r=-1;Q(t.responsive,0,3,`${e}.responsive`).forEach((o,s)=>{let a=b(o,`${e}.responsive[${s}]`);I(a,["breakpoint","layoutItem"],`${e}.responsive[${s}]`);let u=R(a.breakpoint,["sm","md","lg"],`${e}.responsive[${s}].breakpoint`);if(n.has(u))throw new g(`${e}.responsive contains duplicate breakpoint`);if(i[u]<=r)throw new g(`${e}.responsive must use strictly increasing breakpoint order`);n.add(u),r=i[u],Kr(a.layoutItem,`${e}.responsive[${s}].layoutItem`)})}function Gr(t,e,n){be(t.columns,`${e}.columns`).forEach((i,r)=>{let o=b(i,`${e}.columns[${r}]`);I(o,["key","label","fieldId"],`${e}.columns[${r}]`),D(o.key,`${e}.columns[${r}].key`),ue(o.label,`${e}.columns[${r}].label`),o.fieldId!==null&&H(o.fieldId,`${e}.columns[${r}].fieldId`)}),be(t.rows,`${e}.rows`).forEach((i,r)=>{let o=b(i,`${e}.rows[${r}]`);I(o,["id","cells"],`${e}.rows[${r}]`),x(o.id,`${e}.rows[${r}].id`,n),be(o.cells,`${e}.rows[${r}].cells`).forEach((s,a)=>{let u=b(s,`${e}.rows[${r}].cells[${a}]`);I(u,["columnKey","value"],`${e}.rows[${r}].cells[${a}]`),D(u.columnKey,`${e}.rows[${r}].cells[${a}].columnKey`),M(u.value,`${e}.rows[${r}].cells[${a}].value`)})})}function tt(t,e,n,i,r,o,s){let a=be(t,e);if(a.length<i||a.length>r)throw new g(`${e} must contain between ${i} and ${r} items`);a.forEach((u,d)=>Vt(u,`${e}[${d}]`,n,o,s))}function Vt(t,e,n,i,r){let o=b(t,e),s=R(o.type,["Freeform","Stack","Grid","Form","Text","Input","Button","Table","Divider","Badge"],`${e}.type`),a=["id","name","visibility","layoutItem","responsive","type"],u={Freeform:["children"],Stack:["direction","gap","align","justify","padding","children"],Grid:["columns","gap","padding","columnOverrides","children"],Form:["formDefinitionId","gap","padding","children"],Text:["content","semantic","tone"],Input:["label","placeholder","value","inputType","required","disabled","formDefinitionId","formFieldId"],Button:["label","variant","size","disabled","iconName"],Table:["columns","rows","density"],Divider:["spacing","tone"],Badge:["label","tone","iconName"]};I(o,[...a,...u[s]],e,s==="Freeform"?["grids"]:[]),Jr(o,e);let d=b(o.layoutItem,`${e}.layoutItem`),m=Object.hasOwn(d,"position");if(i==="required"&&!m)throw new g(`${e}.layoutItem.position is required inside a Freeform container`);if(i==="forbidden"&&m)throw new g(`${e}.layoutItem.position is forbidden on a document or component root`);switch(x(o.id,`${e}.id`,n),s){case"Freeform":{let l=b(d.width,`${e}.layoutItem.width`),c=b(d.height,`${e}.layoutItem.height`);if(l.unit!=="px"||c.unit!=="px"||Number(l.value)<=0||Number(c.value)<=0)throw new g(`${e} Freeform width and height must be non-zero px lengths`);let f=Number(l.value),p=Number(c.value);Wr(o.grids,`${e}.grids`,f,p,n,r),tt(o.children,`${e}.children`,n,0,500,"required",r);return}case"Stack":R(o.direction,["row","column"],`${e}.direction`),T(o.gap,0,128,`${e}.gap`),R(o.align,["start","center","end","stretch"],`${e}.align`),R(o.justify,["start","center","end","between"],`${e}.justify`),Tt(o.padding,`${e}.padding`),tt(o.children,`${e}.children`,n,0,500,"optional",r);return;case"Grid":{T(o.columns,1,12,`${e}.columns`),T(o.gap,0,128,`${e}.gap`),Tt(o.padding,`${e}.padding`);let l=be(o.columnOverrides,`${e}.columnOverrides`);if(l.length>3)throw new g(`${e}.columnOverrides must contain at most 3 items`);let c=null;l.forEach((f,p)=>{let h=`${e}.columnOverrides[${p}]`,y=b(f,h);I(y,["minWidth","columns"],h);let _=T(y.minWidth,320,2560,`${h}.minWidth`);if(T(y.columns,1,12,`${h}.columns`),c!==null&&_<=c)throw new g(`${e}.columnOverrides must use strictly increasing minWidth values`);c=_}),tt(o.children,`${e}.children`,n,0,500,"optional",r);return}case"Form":H(o.formDefinitionId,`${e}.formDefinitionId`),T(o.gap,0,128,`${e}.gap`),Tt(o.padding,`${e}.padding`),tt(o.children,`${e}.children`,n,1,200,"optional",r);return;case"Text":M(o.content,`${e}.content`),R(o.semantic,["heading","body","label","caption"],`${e}.semantic`),R(o.tone,["default","muted","success","warning","danger"],`${e}.tone`);return;case"Input":if(ue(o.label,`${e}.label`),M(o.placeholder,`${e}.placeholder`),M(o.value,`${e}.value`),R(o.inputType,["text","number","email"],`${e}.inputType`),De(o.required,`${e}.required`),De(o.disabled,`${e}.disabled`),o.formDefinitionId===null!=(o.formFieldId===null))throw new g(`${e} form bindings must be supplied together`);o.formDefinitionId!==null&&H(o.formDefinitionId,`${e}.formDefinitionId`),o.formFieldId!==null&&H(o.formFieldId,`${e}.formFieldId`);return;case"Button":ue(o.label,`${e}.label`),R(o.variant,["primary","secondary","danger","ghost"],`${e}.variant`),R(o.size,["small","medium","large"],`${e}.size`),De(o.disabled,`${e}.disabled`),o.iconName!==null&&ue(o.iconName,`${e}.iconName`);return;case"Divider":T(o.spacing,0,64,`${e}.spacing`),R(o.tone,["default","muted"],`${e}.tone`);return;case"Badge":if(ue(o.label,`${e}.label`),String(o.label).length>40)throw new g(`${e}.label must be at most 40 characters`);R(o.tone,["default","success","warning","danger"],`${e}.tone`),o.iconName!==null&&ue(o.iconName,`${e}.iconName`);return;case"Table":Gr(o,e,n),R(o.density,["compact","comfortable"],`${e}.density`)}}function Pt(t,e){if(e.set(t.id,t),X(t))for(let n of t.children)Pt(n,e)}function Yr(t){let e=b(t,"document.settings.shell"),n=R(e.kind,["sidebar","topbar"],"document.settings.shell.kind"),i=["kind","title","accentColorTokenKey","navigationBackgroundColorTokenKey","contentBackgroundColorTokenKey","surfaceColorTokenKey"];I(e,n==="sidebar"?[...i,"navigationWidth","expandedMinWidth"]:i,"document.settings.shell"),we(e.title,80,"document.settings.shell.title");let r=[D(e.accentColorTokenKey,"document.settings.shell.accentColorTokenKey"),D(e.navigationBackgroundColorTokenKey,"document.settings.shell.navigationBackgroundColorTokenKey"),D(e.contentBackgroundColorTokenKey,"document.settings.shell.contentBackgroundColorTokenKey"),D(e.surfaceColorTokenKey,"document.settings.shell.surfaceColorTokenKey")];return n==="sidebar"&&(T(e.navigationWidth,160,400,"document.settings.shell.navigationWidth"),T(e.expandedMinWidth,320,2560,"document.settings.shell.expandedMinWidth")),r}function Xr(t){let e=new Set(t.pages.map(o=>o.id));if(e.size!==t.pages.length)throw new g("pages contain duplicate IDs");if(t.runtime.pageIds.length!==t.pages.length||t.runtime.pageIds.some((o,s)=>t.pages[s]?.id!==o))throw new g("runtime page order must match document page order");for(let o of t.navigation.items)if(!e.has(o.targetPageId))throw new g(`navigation ${o.id} references an unknown page`);let n=new Map;for(let o of t.pages)Pt(o.root,n);for(let o of t.componentDefinitions)Pt(o.root,n);let i=new Map(t.runtime.entitySchemas.map(o=>[o.id,o])),r=new Set;for(let o of t.runtime.viewBindings){let s=`${o.nodeId}:${o.target}`;if(r.has(s))throw new g(`view bindings contain duplicate node target ${s}`);r.add(s);let a=n.get(o.nodeId);if(a===void 0)throw new g(`view binding ${o.id} references an unknown node`);if(o.target==="tableRows"&&a.type!=="Table")throw new g(`view binding ${o.id} requires a Table node`);if(o.target==="tableRows"&&a.type==="Table"){let u=i.get(o.schemaId);if(u===void 0)throw new g(`view binding ${o.id} references an unknown schema`);let d=new Set(u.fields.map(m=>m.id));for(let m of a.columns){if(m.fieldId===null)throw new g(`runtime table ${a.id} column ${m.key} requires a schema field`);if(!d.has(m.fieldId))throw new g(`runtime table ${a.id} column ${m.key} field is not in its binding schema`)}}if(o.target==="textContent"&&a.type!=="Text")throw new g(`view binding ${o.id} requires a Text node`)}for(let o of t.runtime.rules){let s=n.get(o.trigger.nodeId);if(s===void 0)throw new g(`rule ${o.id} references an unknown node`);if(o.trigger.event==="rowActivated"&&s.type!=="Table")throw new g(`rule ${o.id} row activation requires a Table node`);if((o.trigger.event==="click"||o.trigger.event==="submit")&&s.type!=="Button")throw new g(`rule ${o.id} activation requires a Button node`)}}function Zr(t,e){t.roles.forEach((n,i)=>x(n.id,`document.runtime.roles[${i}].id`,e)),t.variables.forEach((n,i)=>x(n.id,`document.runtime.variables[${i}].id`,e)),t.entitySchemas.forEach((n,i)=>{x(n.id,`document.runtime.entitySchemas[${i}].id`,e),n.fields.forEach((r,o)=>x(r.id,`document.runtime.entitySchemas[${i}].fields[${o}].id`,e))}),t.forms.forEach((n,i)=>{x(n.id,`document.runtime.forms[${i}].id`,e),n.fields.forEach((r,o)=>x(r.id,`document.runtime.forms[${i}].fields[${o}].id`,e))}),t.viewBindings.forEach((n,i)=>x(n.id,`document.runtime.viewBindings[${i}].id`,e)),t.rules.forEach((n,i)=>x(n.id,`document.runtime.rules[${i}].id`,e)),t.scenarios.forEach((n,i)=>{x(n.id,`document.runtime.scenarios[${i}].id`,e),n.entityFixtures.forEach((r,o)=>r.entities.forEach((s,a)=>x(s.id,`document.runtime.scenarios[${i}].entityFixtures[${o}].entities[${a}].id`,e)))})}function Zn(t){let e=b(t,"document");if(I(e,["schemaVersion","id","title","locale","settings","tokens","componentDefinitions","pages","navigation","flows","runtime","assetRefs"],"document"),e.schemaVersion!==1)throw new g("document.schemaVersion must equal 1");let n=new Set;x(e.id,"document.id",n),we(e.title,120,"document.title"),R(e.locale,["zh-CN","en-US"],"document.locale");let i=b(e.settings,"document.settings");I(i,["defaultViewport","theme","shell"],"document.settings"),R(i.defaultViewport,["desktop","tablet","mobile"],"document.settings.defaultViewport"),R(i.theme,["light","dark","system"],"document.settings.theme");let r=Yr(i.shell),o=b(e.tokens,"document.tokens");I(o,["colors","spacing"],"document.tokens");let s=new Set;for(let l of["colors","spacing"]){let c=l==="colors"?100:50;Q(o[l],0,c,`document.tokens.${l}`).forEach((f,p)=>{let h=b(f,`document.tokens.${l}[${p}]`);I(h,["key","value"],`document.tokens.${l}[${p}]`);let y=D(h.key,`document.tokens.${l}[${p}].key`);l==="colors"&&s.add(y),we(h.value,120,`document.tokens.${l}[${p}].value`)})}let a=r.filter(l=>!s.has(l));if(a.length>0)throw new g(`document.settings.shell references unknown color token keys: ${a.join(", ")}`);Q(e.componentDefinitions,0,50,"document.componentDefinitions").forEach((l,c)=>{let f=b(l,`document.componentDefinitions[${c}]`);I(f,["id","key","root"],`document.componentDefinitions[${c}]`),x(f.id,`document.componentDefinitions[${c}].id`,n),D(f.key,`document.componentDefinitions[${c}].key`),Vt(f.root,`document.componentDefinitions[${c}].root`,n,"forbidden",s)}),Q(e.pages,1,20,"document.pages").forEach((l,c)=>{let f=b(l,`document.pages[${c}]`);I(f,["id","key","title","route","viewport","root"],`document.pages[${c}]`),x(f.id,`document.pages[${c}].id`,n),D(f.key,`document.pages[${c}].key`),we(f.title,80,`document.pages[${c}].title`);let p=M(f.route,`document.pages[${c}].route`);if(!/^\\/(?:[A-Za-z0-9._~-]+(?:\\/[A-Za-z0-9._~-]+)*)?$/u.test(p))throw new g(`document.pages[${c}].route is invalid`);let h=b(f.viewport,`document.pages[${c}].viewport`);I(h,["width","height"],`document.pages[${c}].viewport`),T(h.width,320,2560,`document.pages[${c}].viewport.width`),T(h.height,480,2160,`document.pages[${c}].viewport.height`),Vt(f.root,`document.pages[${c}].root`,n,"forbidden",s)});let u=b(e.navigation,"document.navigation");I(u,["items"],"document.navigation"),Q(u.items,0,20,"document.navigation.items").forEach((l,c)=>{let f=b(l,`document.navigation.items[${c}]`);I(f,["id","key","label","targetPageId"],`document.navigation.items[${c}]`),x(f.id,`document.navigation.items[${c}].id`,n),D(f.key,`document.navigation.items[${c}].key`),we(f.label,80,`document.navigation.items[${c}].label`),H(f.targetPageId,`document.navigation.items[${c}].targetPageId`)}),Q(e.flows,0,100,"document.flows").forEach((l,c)=>{let f=b(l,`document.flows[${c}]`);I(f,["id","key","ruleId","fromNodeId","toPageId"],`document.flows[${c}]`),x(f.id,`document.flows[${c}].id`,n),D(f.key,`document.flows[${c}].key`),H(f.ruleId,`document.flows[${c}].ruleId`),H(f.fromNodeId,`document.flows[${c}].fromNodeId`),f.toPageId!==null&&H(f.toPageId,`document.flows[${c}].toPageId`)});let d=Yn(e.runtime);Zr(d,n),Q(e.assetRefs,0,200,"document.assetRefs").forEach((l,c)=>{let f=b(l,`document.assetRefs[${c}]`);I(f,["id","contentHash","mediaType","alt"],`document.assetRefs[${c}]`),x(f.id,`document.assetRefs[${c}].id`,n);let p=M(f.contentHash,`document.assetRefs[${c}].contentHash`);if(!/^sha256:[0-9a-f]{64}$/u.test(p))throw new g(`document.assetRefs[${c}].contentHash is invalid`);R(f.mediaType,["image/png","image/jpeg","image/webp","image/svg+xml"],`document.assetRefs[${c}].mediaType`),M(f.alt,`document.assetRefs[${c}].alt`)});let m=structuredClone({...e,runtime:d});return Xr(m),m}var Qr=["click","submit","rowActivated"];function At(t,e){let n=new Set(t.runtime.rules.filter(i=>i.enabled&&i.trigger.nodeId===e).map(i=>i.trigger.event));return Qr.filter(i=>n.has(i))}function Qn(t,e){return At(t,e).flatMap(n=>n==="rowActivated"?[]:[{kind:"nodeActivated",nodeId:e,event:n}])}function $e(t,e,n){let i=t.querySelector(e);if(!(i instanceof n))throw new Error(`Published prototype is missing ${e}`);return i}function ei(t){switch(t.type){case"null":return"";case"boolean":return t.value?"true":"false";case"integer":return String(t.value);case"string":case"enum":return t.value;case"entityRef":return t.entityId}}function ti(t){let e=document.querySelector(`[data-prototype-node-id="${t}"]`);return e instanceof HTMLElement?e:null}function eo(t,e){let n=i=>{if(i.id===e)return i.type==="Table"?i:null;if(X(i))for(let r of i.children){let o=n(r);if(o!==null)return o}return null};for(let i of t.pages){let r=n(i.root);if(r!==null)return r}return null}function to(t,e,n){let i=eo(t.document,e);if(i===null)throw new Error(`Runtime table ${e} does not exist`);let o=ti(e)?.querySelector("tbody");if(!(o instanceof HTMLTableSectionElement))throw new Error(`Runtime table ${e} has no table body`);let s=t.document.runtime.viewBindings.find(u=>u.nodeId===e&&u.target==="tableRows");if(s===void 0||s.target!=="tableRows")throw new Error(`Runtime table ${e} has no rows binding`);let a=[];for(let u of n){let d=document.createElement("tr");d.dataset.entityId=u.id,d.dataset.schemaId=u.schemaId;for(let m of i.columns){if(m.fieldId===null)throw new Error(`Runtime table ${e} column ${m.key} has no schema field binding`);let l=u.fields.find(f=>f.fieldId===m.fieldId);if(l===void 0)throw new Error(`Runtime entity ${u.id} has no value for table field ${m.fieldId}`);let c=document.createElement("td");c.textContent=ei(l.value),d.append(c)}a.push(d)}o.replaceChildren(...a)}function Dt(t){let e=t.manualPageId??t.state.currentPageId;document.querySelectorAll("[data-prototype-page-id]").forEach(u=>{u.dataset.active=String(u.dataset.prototypePageId===e)}),document.querySelectorAll("[data-navigation-target]").forEach(u=>{u.setAttribute("aria-current",u.dataset.navigationTarget===e?"page":"false")});let n=t.document.pages.find(u=>u.id===e),i=$e(document,"[data-current-page-title]",HTMLElement);i.textContent=n?.title??t.document.title;let r=t.document.runtime.roles.find(u=>u.id===t.state.actorRoleId),o=$e(document,"[data-role-select]",HTMLSelectElement);o.value=t.state.actorRoleId,o.disabled=!t.state.allowSimulatedRoleSwitch,$e(document,"[data-current-role-label]",HTMLElement).textContent=r?.label??t.state.actorRoleId;let s=t.state.notifications.at(-1),a=$e(document,"[data-runtime-notification]",HTMLElement);a.dataset.visible=String(s!==void 0),a.dataset.level=s?.level??"info",a.textContent=s?.message??"";for(let u of t.viewModel.nodes){let d=ti(u.nodeId);if(d!==null)for(let m of u.properties)switch(m.target){case"textContent":d.textContent=ei(m.value);break;case"visibility":d.hidden=!m.value.value;break;case"tableRows":to(t,u.nodeId,m.rows);break}}for(let u of t.state.formStates)for(let d of t.inputBindings.values()){if(d.formId!==u.formId)continue;let m=document.querySelector(`[data-runtime-form-id="${d.formId}"][data-runtime-field-id="${d.fieldId}"]`);if(m===null)continue;let l=u.errors.some(c=>c.fieldId===d.fieldId);m.setAttribute("aria-invalid",String(l))}}function ni(t){let e=$e(document,"[data-runtime-error]",HTMLElement);e.hidden=!1,e.textContent=t instanceof Error?t.message:String(t)}async function Ft(t,e){t.eventNo+=1;let n=await Mn(t.document.runtime,t.state,{clientEventId:`${t.state.sessionId}:${t.eventNo}`,expectedSequenceNo:t.state.sequenceNo,events:e});t.state=n.state,t.viewModel=n.viewModel,t.manualPageId=null,Dt(t)}function no(t,e){if(t.valueType==="integer"){let n=Number(e.value);if(!Number.isSafeInteger(n))throw new Error(`${e.value} is not a valid integer`);return{kind:"fieldValueCommitted",nodeId:t.nodeId,formId:t.formId,fieldId:t.fieldId,value:{type:"integer",value:n}}}return{kind:"fieldValueCommitted",nodeId:t.nodeId,formId:t.formId,fieldId:t.fieldId,value:{type:"string",value:e.value}}}function io(t){let e=Promise.resolve(),n=i=>{e=e.then(i).catch(r=>ni(r))};document.querySelectorAll("[data-navigation-target]").forEach(i=>{i.addEventListener("click",()=>{t.manualPageId=i.dataset.navigationTarget??null,Dt(t)})}),t.state.allowSimulatedRoleSwitch&&$e(document,"[data-role-select]",HTMLSelectElement).addEventListener("change",i=>{if(!(i.currentTarget instanceof HTMLSelectElement))return;let r=i.currentTarget.value;n(()=>Ft(t,[{kind:"switchSimulatedRole",roleId:r}]))}),document.querySelectorAll("[data-runtime-node-id]").forEach(i=>{i.addEventListener("click",()=>{let r=i.dataset.runtimeNodeId;r!==void 0&&n(async()=>{let o=Qn(t.document,r);if(o.length===0)return;let s=[];if(o.some(a=>a.event==="submit")){let a=i.closest("[data-prototype-form-id]");if(a===null)throw new Error(`Submit button ${r} is outside a form`);a.querySelectorAll("[data-runtime-field-id]").forEach(u=>{let d=t.inputBindings.get(u.closest("[data-prototype-node-id]")?.dataset.prototypeNodeId??"");d!==void 0&&s.push(no(d,u))})}s.push(...o),await Ft(t,s)})})}),document.addEventListener("click",i=>{let r=i.target;if(!(r instanceof Element))return;let o=r.closest("tr[data-entity-id][data-schema-id]"),s=o?.closest("[data-prototype-node-id]"),a=o?.dataset.entityId,u=o?.dataset.schemaId,d=s?.dataset.prototypeNodeId;a===void 0||u===void 0||d===void 0||n(async()=>{At(t.document,d).includes("rowActivated")&&await Ft(t,[{kind:"tableRowActivated",nodeId:d,entityRef:{type:"entityRef",schemaId:u,entityId:a}}])})})}async function ro(){let t=await fetch("./document.json",{cache:"no-store",credentials:"same-origin"});if(!t.ok)throw new Error(`Published prototype document failed to load (${t.status})`);let e=Zn(await t.json()),n=e.runtime.scenarios[0];if(n===void 0)throw new Error("Published prototype has no runtime scenario");let i=`${e.id}:${n.id}:published`,r=Pn(e.runtime,n.id,i),o={document:e,state:r,viewModel:Qe(e.runtime,r),manualPageId:null,inputBindings:new Map(Bn(e).map(s=>[s.nodeId,s])),eventNo:0};Dt(o),io(o)}ro().catch(t=>ni(t));})();\n'
  );
  const files = rendered.files.map((file) => {
    const bytes = Buffer.from(file.content, "utf8");
    return {
      relativePath: file.relativePath,
      byteSize: bytes.byteLength,
      contentHash: sha256(bytes),
      contentBase64: bytes.toString("base64")
    };
  });
  const descriptors = files.map(({ relativePath, byteSize, contentHash }) => ({
    relativePath,
    byteSize,
    contentHash
  }));
  const bundleHash = sha256(canonicalRuntimeJson(descriptors));
  const visualPreflightReportHash = sha256(canonicalRuntimeJson(rendered.preflight));
  const outputManifest = {
    contractVersion: 1,
    rendererVersion: manifest.rendererVersion,
    rendererEnvironmentVersion: manifest.rendererEnvironmentVersion,
    runtimeCoreVersion: manifest.runtimeCoreVersion,
    runtimeCoreSourceHash: manifest.runtimeCoreSourceHash,
    runtimeCoreBundleHash: manifest.runtimeCoreBundleHash,
    stateMachineKernelVersion: manifest.stateMachineKernelVersion,
    inputManifestHash,
    documentObjectHash: manifest.documentObjectHash,
    artifactId,
    files: descriptors,
    bundleHash,
    visualPreflightReportHash
  };
  return {
    ...identity(),
    requestId,
    action: "render",
    status: "ok",
    result: {
      inputManifestHash,
      outputManifest,
      outputManifestHash: sha256(canonicalRuntimeJson(outputManifest)),
      visualPreflightReport: rendered.preflight,
      visualPreflightReportHash,
      bundleHash,
      files
    }
  };
}
function execute(input) {
  const decoded = record2(JSON.parse(input), "request");
  if (decoded["action"] === "describe") {
    exactKeys2(decoded, ["protocolVersion", "requestId", "action"], "request");
    if (decoded["protocolVersion"] !== PROTOCOL_VERSION) {
      throw new RendererWorkerProtocolError(
        "renderer_request_invalid",
        "renderer protocol version is unsupported"
      );
    }
    return {
      ...identity(),
      requestId: string2(decoded["requestId"], "request.requestId"),
      action: "describe",
      status: "ok",
      result: identity()
    };
  }
  return render(decoded);
}
function failure(error) {
  if (error instanceof RendererWorkerProtocolError || error instanceof PrototypeRendererError) {
    return { code: error.code, message: error.message, internal: false };
  }
  if (error instanceof RendererDocumentCodecError) {
    return { code: "renderer_document_invalid", message: error.message, internal: false };
  }
  return {
    code: "renderer_internal_error",
    message: "renderer failed unexpectedly",
    internal: true
  };
}
async function main() {
  let input = "";
  process.stdin.setEncoding("utf8");
  for await (const chunk of process.stdin) {
    if (typeof chunk !== "string") throw new TypeError("renderer stdin did not decode as UTF-8");
    input += chunk;
    if (Buffer.byteLength(input, "utf8") > MAX_REQUEST_BYTES) {
      throw new RendererWorkerProtocolError(
        "renderer_request_too_large",
        "renderer request exceeds 4 MiB"
      );
    }
  }
  const request = readIdentity(input);
  try {
    process.stdout.write(`${canonicalRuntimeJson(execute(input))}
`);
  } catch (error) {
    const result = failure(error);
    process.stdout.write(
      `${canonicalRuntimeJson({ ...identity(), requestId: request.requestId, action: request.action, status: "error", error: { code: result.code, message: result.message } })}
`
    );
    if (result.internal) {
      process.stderr.write(
        `${error instanceof Error ? error.stack ?? error.message : String(error)}
`
      );
      process.exitCode = 1;
    }
  }
}
void main().catch((error) => {
  process.stderr.write(
    `${error instanceof Error ? error.stack ?? error.message : String(error)}
`
  );
  process.exitCode = 1;
});
