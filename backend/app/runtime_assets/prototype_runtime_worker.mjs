// node_modules/xstate/dist/xstate-dev.esm.js
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

// node_modules/xstate/dist/raise-5fb0c8ca.esm.js
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
  function stop2(_args, _params) {
  }
  stop2.type = "xstate.stopChild";
  stop2.actorRef = actorRef;
  stop2.resolve = resolveStop;
  stop2.execute = executeStop;
  return stop2;
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

// node_modules/xstate/dist/assign-29f23f4d.esm.js
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

// node_modules/xstate/dist/StateMachine-5f345bba.esm.js
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

// node_modules/xstate/dist/log-79409d72.esm.js
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

// node_modules/xstate/dist/xstate.esm.js
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

// src/features/prototype/runtime/canonical.ts
var textEncoder = new TextEncoder();
function compareUnicodeCodePoints(left, right) {
  const leftPoints = Array.from(left);
  const rightPoints = Array.from(right);
  const length = Math.min(leftPoints.length, rightPoints.length);
  for (let index = 0; index < length; index += 1) {
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
function digestBytesToHex(bytes) {
  return Array.from(new Uint8Array(bytes), (byte) => byte.toString(16).padStart(2, "0")).join("");
}
function canonicalRuntimeJson(value) {
  return canonicalize(value);
}
async function hashRuntimeValue(value) {
  const canonical = canonicalRuntimeJson(value);
  const digest = await globalThis.crypto.subtle.digest("SHA-256", textEncoder.encode(canonical));
  return `sha256:${digestBytesToHex(digest)}`;
}
function uuidToBytes(uuid) {
  const hex = uuid.replaceAll("-", "");
  if (!/^[0-9a-f]{32}$/u.test(hex)) {
    throw new TypeError(`Invalid UUID namespace: ${uuid}`);
  }
  const bytes = new Uint8Array(16);
  for (let index = 0; index < bytes.length; index += 1) {
    const offset = index * 2;
    bytes[index] = Number.parseInt(hex.slice(offset, offset + 2), 16);
  }
  return bytes;
}
function bytesToUuid(bytes) {
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(
    16,
    20
  )}-${hex.slice(20)}`;
}
async function deterministicUuidV5(namespace, name) {
  const namespaceBytes = uuidToBytes(namespace);
  const nameBytes = textEncoder.encode(name);
  const input = new Uint8Array(namespaceBytes.length + nameBytes.length);
  input.set(namespaceBytes);
  input.set(nameBytes, namespaceBytes.length);
  const digest = new Uint8Array(await globalThis.crypto.subtle.digest("SHA-1", input));
  const uuidBytes = digest.slice(0, 16);
  uuidBytes[6] = (uuidBytes[6] ?? 0) & 15 | 80;
  uuidBytes[8] = (uuidBytes[8] ?? 0) & 63 | 128;
  return bytesToUuid(uuidBytes);
}

// src/features/prototype/runtime/runtimeCore.ts
var RUNTIME_CORE_VERSION = "0.2.0-spike";
var XSTATE_KERNEL_VERSION = "5.32.4";
var RUNTIME_ENTITY_NAMESPACE = "1af0c23d-70d2-5fd5-aad8-3f1eafbb10a1";
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
function assertUniqueIds(items, label) {
  return assertUniqueValues(
    items.map((item) => item.id),
    label
  );
}
function assertUniqueValues(values, label) {
  const seen = /* @__PURE__ */ new Set();
  const errors = [];
  for (const value of values) {
    if (seen.has(value)) {
      errors.push(`${label} contains duplicate id ${value}`);
    }
    seen.add(value);
  }
  return errors;
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
function valueExpressionUsesEventEntityRef(expression) {
  switch (expression.kind) {
    case "eventEntityRef":
      return true;
    case "entityField":
      return valueExpressionUsesEventEntityRef(expression.entityRef);
    case "literal":
    case "variable":
    case "formField":
      return false;
  }
}
function predicateUsesEventEntityRef(predicate) {
  switch (predicate.kind) {
    case "all":
      return predicate.items.some(predicateUsesEventEntityRef);
    case "compare":
      return valueExpressionUsesEventEntityRef(predicate.left) || valueExpressionUsesEventEntityRef(predicate.right);
    case "roleIs":
    case "formValid":
      return false;
  }
}
function validateRuntimeDefinition(definition) {
  const errors = [
    ...assertUniqueValues(definition.pageIds, "pages"),
    ...assertUniqueIds(definition.roles, "roles"),
    ...assertUniqueIds(definition.variables, "variables"),
    ...assertUniqueIds(definition.entitySchemas, "entitySchemas"),
    ...assertUniqueIds(definition.forms, "forms"),
    ...assertUniqueIds(definition.viewBindings, "viewBindings"),
    ...assertUniqueValues(
      definition.viewBindings.map((binding) => `${binding.nodeId}:${binding.target}`),
      "view binding node targets"
    ),
    ...assertUniqueIds(definition.rules, "rules"),
    ...assertUniqueIds(definition.scenarios, "scenarios")
  ];
  const roleIds = new Set(definition.roles.map((role) => role.id));
  const pageIds = new Set(definition.pageIds);
  const schemaIds = new Set(definition.entitySchemas.map((schema) => schema.id));
  for (const variable of definition.variables) {
    if (variable.valueType === "entityRef") {
      if (variable.entitySchemaId === null) {
        errors.push(`variable ${variable.id} entityRef type requires an entity schema`);
      } else if (!schemaIds.has(variable.entitySchemaId)) {
        errors.push(
          `variable ${variable.id} references unknown entity schema ${variable.entitySchemaId}`
        );
      }
    } else if (variable.entitySchemaId !== null) {
      errors.push(`variable ${variable.id} non-entityRef type cannot declare an entity schema`);
    }
    if (!valueMatchesType(variable.defaultValue, variable.valueType, variable.nullable)) {
      errors.push(`variable ${variable.id} default value does not match ${variable.valueType}`);
    } else if (!entityRefMatchesSchema(variable.defaultValue, variable.entitySchemaId)) {
      errors.push(`variable ${variable.id} default entity schema does not match its definition`);
    }
  }
  for (const scenario of definition.scenarios) {
    errors.push(
      ...assertUniqueValues(
        scenario.initialVariables.map((entry) => entry.variableId),
        `scenario ${scenario.id} variables`
      ),
      ...assertUniqueValues(
        scenario.entityFixtures.map((fixture) => fixture.schemaId),
        `scenario ${scenario.id} entity fixtures`
      )
    );
    if (!roleIds.has(scenario.actorRoleId)) {
      errors.push(`scenario ${scenario.id} references unknown role ${scenario.actorRoleId}`);
    }
    if (!pageIds.has(scenario.startPageId)) {
      errors.push(`scenario ${scenario.id} references unknown page ${scenario.startPageId}`);
    }
    for (const value of scenario.initialVariables) {
      const variable = definition.variables.find((candidate) => candidate.id === value.variableId);
      if (variable === void 0) {
        errors.push(`scenario ${scenario.id} references unknown variable ${value.variableId}`);
      } else if (!valueMatchesType(value.value, variable.valueType, variable.nullable)) {
        errors.push(
          `scenario ${scenario.id} variable ${value.variableId} does not match ${variable.valueType}`
        );
      } else if (!entityRefMatchesSchema(value.value, variable.entitySchemaId)) {
        errors.push(
          `scenario ${scenario.id} variable ${value.variableId} entity schema does not match its definition`
        );
      }
    }
    for (const fixture of scenario.entityFixtures) {
      if (!schemaIds.has(fixture.schemaId)) {
        errors.push(`scenario ${scenario.id} references unknown schema ${fixture.schemaId}`);
      }
    }
  }
  for (const rule of definition.rules) {
    if (rule.effects.length === 0) {
      errors.push(`rule ${rule.id} has no effects`);
    }
    for (const effect of [...rule.effects, ...rule.guardFalseEffects]) {
      if (effect.kind !== "createEntity") {
        continue;
      }
      const resultVariable = definition.variables.find(
        (variable) => variable.id === effect.resultVariableId
      );
      if (resultVariable === void 0 || resultVariable.valueType !== "entityRef" || resultVariable.entitySchemaId !== effect.schemaId) {
        errors.push(
          `rule ${rule.id} create-entity result variable does not match schema ${effect.schemaId}`
        );
      }
    }
  }
  for (const binding of definition.viewBindings) {
    if (binding.target === "tableRows" && !schemaIds.has(binding.schemaId)) {
      errors.push(`view binding ${binding.id} references unknown schema ${binding.schemaId}`);
    }
    if (binding.target === "textContent" && valueExpressionUsesEventEntityRef(binding.value) || binding.target === "visibility" && predicateUsesEventEntityRef(binding.predicate)) {
      errors.push(`view binding ${binding.id} cannot reference the current event entity`);
    }
  }
  for (const form of definition.forms) {
    errors.push(...assertUniqueIds(form.fields, `form ${form.id} fields`));
  }
  for (const schema of definition.entitySchemas) {
    errors.push(...assertUniqueIds(schema.fields, `schema ${schema.id} fields`));
  }
  if (definition.roles.length === 0) {
    errors.push("runtime definition requires at least one role");
  }
  if (definition.scenarios.length === 0) {
    errors.push("runtime definition requires at least one scenario");
  }
  return errors;
}
function validateRuntimeState(definition, state) {
  const errors = [];
  if (state.runtimeCoreVersion !== RUNTIME_CORE_VERSION) {
    errors.push(
      `runtime core version ${state.runtimeCoreVersion} does not match ${RUNTIME_CORE_VERSION}`
    );
  }
  if (state.stateMachineKernelVersion !== XSTATE_KERNEL_VERSION) {
    errors.push(
      `state machine kernel version ${state.stateMachineKernelVersion} does not match ${XSTATE_KERNEL_VERSION}`
    );
  }
  if (state.sessionId.length === 0) {
    errors.push("runtime session id must not be empty");
  }
  if (state.sequenceNo < 0) {
    errors.push("runtime sequence must not be negative");
  }
  if (!definition.roles.some((role) => role.id === state.actorRoleId)) {
    errors.push(`runtime state references unknown role ${state.actorRoleId}`);
  }
  if (!definition.pageIds.includes(state.currentPageId)) {
    errors.push(`runtime state references unknown current page ${state.currentPageId}`);
  }
  for (const pageId of state.navigationStack) {
    if (!definition.pageIds.includes(pageId)) {
      errors.push(`runtime navigation stack references unknown page ${pageId}`);
    }
  }
  const scenario = definition.scenarios.find((candidate) => candidate.id === state.scenarioId);
  if (scenario === void 0) {
    errors.push(`runtime state references unknown scenario ${state.scenarioId}`);
  } else if (state.allowSimulatedRoleSwitch !== scenario.allowSimulatedRoleSwitch) {
    errors.push(`runtime state role-switch policy does not match scenario ${state.scenarioId}`);
  }
  errors.push(
    ...assertUniqueValues(
      state.variableValues.map((entry) => entry.variableId),
      "runtime variable values"
    )
  );
  for (const definitionVariable of definition.variables) {
    if (!state.variableValues.some((entry) => entry.variableId === definitionVariable.id)) {
      errors.push(`runtime state is missing variable ${definitionVariable.id}`);
    }
  }
  for (const entry of state.variableValues) {
    const variable = definition.variables.find((candidate) => candidate.id === entry.variableId);
    if (variable === void 0) {
      errors.push(`runtime state contains unknown variable ${entry.variableId}`);
    } else if (!valueMatchesType(entry.value, variable.valueType, variable.nullable)) {
      errors.push(`runtime variable ${entry.variableId} does not match ${variable.valueType}`);
    } else if (!entityRefMatchesSchema(entry.value, variable.entitySchemaId)) {
      errors.push(
        `runtime variable ${entry.variableId} entity schema does not match its definition`
      );
    }
  }
  errors.push(
    ...assertUniqueValues(
      state.entitySets.map((set) => set.schemaId),
      "runtime entity sets"
    )
  );
  for (const schema of definition.entitySchemas) {
    if (!state.entitySets.some((set) => set.schemaId === schema.id)) {
      errors.push(`runtime state is missing entity set ${schema.id}`);
    }
  }
  for (const set of state.entitySets) {
    const schema = definition.entitySchemas.find((candidate) => candidate.id === set.schemaId);
    if (schema === void 0) {
      errors.push(`runtime state contains unknown entity set ${set.schemaId}`);
      continue;
    }
    errors.push(
      ...assertUniqueValues(
        set.entities.map((entity) => entity.id),
        `runtime entity set ${set.schemaId}`
      )
    );
    for (const entity of set.entities) {
      if (entity.schemaId !== set.schemaId) {
        errors.push(`runtime entity ${entity.id} schema does not match set ${set.schemaId}`);
      }
      errors.push(
        ...assertUniqueValues(
          entity.fields.map((field) => field.fieldId),
          `runtime entity ${entity.id} fields`
        )
      );
      for (const fieldDefinition of schema.fields) {
        if (!entity.fields.some((field) => field.fieldId === fieldDefinition.id)) {
          errors.push(`runtime entity ${entity.id} is missing field ${fieldDefinition.id}`);
        }
      }
      for (const field of entity.fields) {
        const fieldDefinition = schema.fields.find((candidate) => candidate.id === field.fieldId);
        if (fieldDefinition === void 0) {
          errors.push(`runtime entity ${entity.id} contains unknown field ${field.fieldId}`);
        } else if (!valueMatchesType(field.value, fieldDefinition.valueType, fieldDefinition.nullable)) {
          errors.push(
            `runtime entity ${entity.id} field ${field.fieldId} does not match ${fieldDefinition.valueType}`
          );
        }
      }
    }
  }
  errors.push(
    ...assertUniqueValues(
      state.formStates.map((form) => form.formId),
      "runtime form states"
    )
  );
  for (const formDefinition of definition.forms) {
    if (!state.formStates.some((form) => form.formId === formDefinition.id)) {
      errors.push(`runtime state is missing form ${formDefinition.id}`);
    }
  }
  for (const form of state.formStates) {
    const formDefinition = definition.forms.find((candidate) => candidate.id === form.formId);
    if (formDefinition === void 0) {
      errors.push(`runtime state contains unknown form ${form.formId}`);
      continue;
    }
    errors.push(
      ...assertUniqueValues(
        form.values.map((field) => field.fieldId),
        `runtime form ${form.formId} values`
      )
    );
    for (const fieldDefinition of formDefinition.fields) {
      if (!form.values.some((field) => field.fieldId === fieldDefinition.id)) {
        errors.push(`runtime form ${form.formId} is missing field ${fieldDefinition.id}`);
      }
    }
    for (const field of form.values) {
      const fieldDefinition = formDefinition.fields.find(
        (candidate) => candidate.id === field.fieldId
      );
      if (fieldDefinition === void 0) {
        errors.push(`runtime form ${form.formId} contains unknown field ${field.fieldId}`);
      } else if (field.value.type !== fieldDefinition.valueType) {
        errors.push(
          `runtime form ${form.formId} field ${field.fieldId} does not match ${fieldDefinition.valueType}`
        );
      }
    }
    for (const formError of form.errors) {
      if (!formDefinition.fields.some((field) => field.id === formError.fieldId)) {
        errors.push(
          `runtime form ${form.formId} error references unknown field ${formError.fieldId}`
        );
      }
    }
  }
  errors.push(
    ...assertUniqueValues(
      state.notifications.map((notification) => notification.id),
      "runtime notifications"
    )
  );
  return errors;
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
function createInitialRuntimeState(definition, scenarioId, sessionId) {
  const validationErrors = validateRuntimeDefinition(definition);
  if (validationErrors.length > 0) {
    throw new RuntimeCoreError("runtime_definition_invalid", validationErrors.join("; "));
  }
  const scenario = requireItem(
    definition.scenarios.find((candidate) => candidate.id === scenarioId),
    "runtime_scenario_missing",
    `Unknown runtime scenario ${scenarioId}`
  );
  const initialVariableById = new Map(
    scenario.initialVariables.map((entry) => [entry.variableId, entry.value])
  );
  const state = {
    runtimeStateSchemaVersion: 1,
    sessionId,
    scenarioId,
    runtimeCoreVersion: RUNTIME_CORE_VERSION,
    stateMachineKernelVersion: XSTATE_KERNEL_VERSION,
    sequenceNo: 0,
    actorRoleId: scenario.actorRoleId,
    currentPageId: scenario.startPageId,
    navigationStack: [],
    variableValues: definition.variables.map((variable) => ({
      variableId: variable.id,
      value: cloneRuntimeValue(initialVariableById.get(variable.id) ?? variable.defaultValue)
    })),
    entitySets: definition.entitySchemas.map((schema) => {
      const fixture = scenario.entityFixtures.find((candidate) => candidate.schemaId === schema.id);
      return {
        schemaId: schema.id,
        entities: fixture === void 0 ? [] : fixture.entities.map(cloneEntity)
      };
    }),
    formStates: definition.forms.map((form) => ({
      formId: form.id,
      values: form.fields.map((field) => ({
        fieldId: field.id,
        value: cloneRuntimeValue(field.initialValue)
      })),
      errors: []
    })),
    notifications: [],
    allowSimulatedRoleSwitch: scenario.allowSimulatedRoleSwitch
  };
  const stateErrors = validateRuntimeState(definition, state);
  if (stateErrors.length > 0) {
    throw new RuntimeCoreError("runtime_state_invalid", stateErrors.join("; "));
  }
  return state;
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
async function prepareRuntimeAllocations(definition, state, batch) {
  const pending = [];
  for (const [eventIndex, event] of batch.events.entries()) {
    const rule = findRuleForEvent(definition, event);
    if (rule === null) {
      continue;
    }
    const branches = ["effects", "guardFalseEffects"];
    for (const branch of branches) {
      for (const [effectIndex, effect] of rule[branch].entries()) {
        if (effect.kind !== "createEntity") {
          continue;
        }
        const key = `${eventIndex}:${branch}:${effectIndex}`;
        const name = `${state.sessionId}:${state.sequenceNo + 1}:${key}`;
        pending.push(
          deterministicUuidV5(RUNTIME_ENTITY_NAMESPACE, name).then((entityId) => ({
            key,
            entityId
          }))
        );
      }
    }
  }
  return Promise.all(pending);
}
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
async function applyRuntimeEventBatch(definition, state, batch) {
  const definitionErrors = validateRuntimeDefinition(definition);
  if (definitionErrors.length > 0) {
    throw new RuntimeCoreError("runtime_definition_invalid", definitionErrors.join("; "));
  }
  const stateErrors = validateRuntimeState(definition, state);
  if (stateErrors.length > 0) {
    throw new RuntimeCoreError("runtime_state_invalid", stateErrors.join("; "));
  }
  if (batch.expectedSequenceNo !== state.sequenceNo) {
    throw new RuntimeCoreError(
      "runtime_sequence_conflict",
      `Expected runtime sequence ${batch.expectedSequenceNo}, current is ${state.sequenceNo}`
    );
  }
  if (batch.events.length === 0 || batch.events.length > 20) {
    throw new RuntimeCoreError(
      "runtime_event_batch_size_invalid",
      "Runtime event batch must contain between 1 and 20 events"
    );
  }
  const baseStateHash = await hashRuntimeValue(state);
  const allocations = await prepareRuntimeAllocations(definition, state, batch);
  const actor = createActor(runtimeMachine, { input: { definition, state } });
  let transitionError;
  let transitionFailed = false;
  const subscription = actor.subscribe({
    error: (error) => {
      transitionFailed = true;
      transitionError = error;
    }
  });
  actor.start();
  actor.send({ type: "runtime.eventBatch", batch, allocations });
  const reduction = actor.getSnapshot().context.reduction;
  subscription.unsubscribe();
  actor.stop();
  if (transitionFailed) {
    throw transitionError;
  }
  if (reduction === null) {
    throw new RuntimeCoreError(
      "runtime_transition_missing",
      "XState runtime transition produced no reduction"
    );
  }
  const viewModel = deriveRuntimeViewModel(definition, reduction.state);
  const [resultStateHash, resultViewModelHash, effects] = await Promise.all([
    hashRuntimeValue(reduction.state),
    hashRuntimeValue(viewModel),
    Promise.all(
      reduction.effectTraces.map(async (trace) => ({
        eventIndex: trace.eventIndex,
        effectIndex: trace.effectIndex,
        effectKind: trace.effectKind,
        beforeStateHash: await hashRuntimeValue(trace.beforeState),
        afterStateHash: await hashRuntimeValue(trace.afterState)
      }))
    )
  ]);
  return {
    state: reduction.state,
    viewModel,
    report: {
      clientEventId: batch.clientEventId,
      baseSequenceNo: state.sequenceNo,
      resultSequenceNo: reduction.state.sequenceNo,
      outcome: reduction.outcome,
      matchedRuleIds: reduction.matchedRuleIds,
      baseStateHash,
      resultStateHash,
      resultViewModelHash,
      effects
    }
  };
}

// src/lib/utils.tsx
function safeJsonParse(input) {
  try {
    return JSON.parse(input);
  } catch {
    return null;
  }
}
function isRecord(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

// src/features/prototype/runtime/runtimeStateCodec.ts
var RuntimeStateCodecError = class extends Error {
  constructor(message) {
    super(message);
    this.name = "RuntimeStateCodecError";
  }
};
function isRecord2(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function requireRecord(value, path) {
  if (!isRecord2(value)) {
    throw new RuntimeStateCodecError(`${path} must be an object`);
  }
  return value;
}
function requireExactKeys(record, expectedKeys, path) {
  const expected = new Set(expectedKeys);
  for (const key of Object.keys(record)) {
    if (!expected.has(key)) {
      throw new RuntimeStateCodecError(`${path} contains unknown field ${key}`);
    }
  }
  for (const key of expectedKeys) {
    if (!Object.hasOwn(record, key)) {
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
  const record = requireRecord(value, path);
  const type = requireLiteral(
    record["type"],
    ["null", "boolean", "integer", "string", "enum", "entityRef"],
    `${path}.type`
  );
  switch (type) {
    case "null":
      requireExactKeys(record, ["type"], path);
      return { type: "null" };
    case "boolean":
      requireExactKeys(record, ["type", "value"], path);
      return { type: "boolean", value: requireBoolean(record["value"], `${path}.value`) };
    case "integer":
      requireExactKeys(record, ["type", "value"], path);
      return { type: "integer", value: requireSafeInteger(record["value"], `${path}.value`) };
    case "string":
      requireExactKeys(record, ["type", "value"], path);
      return { type: "string", value: requireString(record["value"], `${path}.value`) };
    case "enum":
      requireExactKeys(record, ["type", "value"], path);
      return { type: "enum", value: requireString(record["value"], `${path}.value`) };
    case "entityRef":
      requireExactKeys(record, ["type", "schemaId", "entityId"], path);
      return {
        type: "entityRef",
        schemaId: requireString(record["schemaId"], `${path}.schemaId`),
        entityId: requireString(record["entityId"], `${path}.entityId`)
      };
  }
}
function parseFieldValue(value, path) {
  const record = requireRecord(value, path);
  requireExactKeys(record, ["fieldId", "value"], path);
  return {
    fieldId: requireString(record["fieldId"], `${path}.fieldId`),
    value: parseRuntimeValue(record["value"], `${path}.value`)
  };
}
function parseVariableValue(value, path) {
  const record = requireRecord(value, path);
  requireExactKeys(record, ["variableId", "value"], path);
  return {
    variableId: requireString(record["variableId"], `${path}.variableId`),
    value: parseRuntimeValue(record["value"], `${path}.value`)
  };
}
function parseEntity(value, path) {
  const record = requireRecord(value, path);
  requireExactKeys(record, ["id", "schemaId", "fields"], path);
  return {
    id: requireString(record["id"], `${path}.id`),
    schemaId: requireString(record["schemaId"], `${path}.schemaId`),
    fields: requireArray(record["fields"], `${path}.fields`).map(
      (field, index) => parseFieldValue(field, `${path}.fields[${index}]`)
    )
  };
}
function parseEntitySet(value, path) {
  const record = requireRecord(value, path);
  requireExactKeys(record, ["schemaId", "entities"], path);
  return {
    schemaId: requireString(record["schemaId"], `${path}.schemaId`),
    entities: requireArray(record["entities"], `${path}.entities`).map(
      (entity, index) => parseEntity(entity, `${path}.entities[${index}]`)
    )
  };
}
function parseFormError(value, path) {
  const record = requireRecord(value, path);
  requireExactKeys(record, ["fieldId", "code"], path);
  return {
    fieldId: requireString(record["fieldId"], `${path}.fieldId`),
    code: requireLiteral(
      record["code"],
      ["required", "min_integer", "type_mismatch"],
      `${path}.code`
    )
  };
}
function parseFormState(value, path) {
  const record = requireRecord(value, path);
  requireExactKeys(record, ["formId", "values", "errors"], path);
  return {
    formId: requireString(record["formId"], `${path}.formId`),
    values: requireArray(record["values"], `${path}.values`).map(
      (field, index) => parseFieldValue(field, `${path}.values[${index}]`)
    ),
    errors: requireArray(record["errors"], `${path}.errors`).map(
      (error, index) => parseFormError(error, `${path}.errors[${index}]`)
    )
  };
}
function parseNotification(value, path) {
  const record = requireRecord(value, path);
  requireExactKeys(record, ["id", "level", "message"], path);
  return {
    id: requireString(record["id"], `${path}.id`),
    level: requireLiteral(
      record["level"],
      ["info", "success", "warning", "error"],
      `${path}.level`
    ),
    message: requireString(record["message"], `${path}.message`)
  };
}
function parsePrototypeRuntimeState(value) {
  const record = requireRecord(value, "runtimeState");
  requireExactKeys(
    record,
    [
      "runtimeStateSchemaVersion",
      "sessionId",
      "scenarioId",
      "runtimeCoreVersion",
      "stateMachineKernelVersion",
      "sequenceNo",
      "actorRoleId",
      "currentPageId",
      "navigationStack",
      "variableValues",
      "entitySets",
      "formStates",
      "notifications",
      "allowSimulatedRoleSwitch"
    ],
    "runtimeState"
  );
  if (record["runtimeStateSchemaVersion"] !== 1) {
    throw new RuntimeStateCodecError("runtimeState.runtimeStateSchemaVersion must equal 1");
  }
  return {
    runtimeStateSchemaVersion: 1,
    sessionId: requireString(record["sessionId"], "runtimeState.sessionId"),
    scenarioId: requireString(record["scenarioId"], "runtimeState.scenarioId"),
    runtimeCoreVersion: requireString(
      record["runtimeCoreVersion"],
      "runtimeState.runtimeCoreVersion"
    ),
    stateMachineKernelVersion: requireString(
      record["stateMachineKernelVersion"],
      "runtimeState.stateMachineKernelVersion"
    ),
    sequenceNo: requireSafeInteger(record["sequenceNo"], "runtimeState.sequenceNo"),
    actorRoleId: requireString(record["actorRoleId"], "runtimeState.actorRoleId"),
    currentPageId: requireString(record["currentPageId"], "runtimeState.currentPageId"),
    navigationStack: requireArray(record["navigationStack"], "runtimeState.navigationStack").map(
      (pageId, index) => requireString(pageId, `runtimeState.navigationStack[${index}]`)
    ),
    variableValues: requireArray(record["variableValues"], "runtimeState.variableValues").map(
      (entry, index) => parseVariableValue(entry, `runtimeState.variableValues[${index}]`)
    ),
    entitySets: requireArray(record["entitySets"], "runtimeState.entitySets").map(
      (set, index) => parseEntitySet(set, `runtimeState.entitySets[${index}]`)
    ),
    formStates: requireArray(record["formStates"], "runtimeState.formStates").map(
      (form, index) => parseFormState(form, `runtimeState.formStates[${index}]`)
    ),
    notifications: requireArray(record["notifications"], "runtimeState.notifications").map(
      (notification, index) => parseNotification(notification, `runtimeState.notifications[${index}]`)
    ),
    allowSimulatedRoleSwitch: requireBoolean(
      record["allowSimulatedRoleSwitch"],
      "runtimeState.allowSimulatedRoleSwitch"
    )
  };
}
function serializePrototypeRuntimeState(state) {
  return canonicalRuntimeJson(state);
}
function parsePrototypeRuntimeStateJson(input) {
  const decoded = safeJsonParse(input);
  if (decoded === null) {
    throw new RuntimeStateCodecError("runtimeState JSON is invalid");
  }
  return parsePrototypeRuntimeState(decoded);
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
function isRecord3(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function requireRecord2(value, path) {
  if (!isRecord3(value)) {
    throw new RuntimeInputCodecError(`${path} must be an object`);
  }
  return value;
}
function requireExactKeys2(record, expectedKeys, path) {
  const expected = new Set(expectedKeys);
  for (const key of Object.keys(record)) {
    if (!expected.has(key)) {
      throw new RuntimeInputCodecError(`${path} contains unknown field ${key}`);
    }
  }
  for (const key of expectedKeys) {
    if (!Object.hasOwn(record, key)) {
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
  const record = requireRecord2(value, path);
  requireExactKeys2(record, ["id", "key", "label"], path);
  return {
    id: requireNonEmptyString(record["id"], `${path}.id`),
    key: requireNonEmptyString(record["key"], `${path}.key`),
    label: requireString2(record["label"], `${path}.label`)
  };
}
function parseVariable(value, path) {
  const record = requireRecord2(value, path);
  requireExactKeys2(
    record,
    ["id", "key", "valueType", "nullable", "entitySchemaId", "defaultValue"],
    path
  );
  return {
    id: requireNonEmptyString(record["id"], `${path}.id`),
    key: requireNonEmptyString(record["key"], `${path}.key`),
    valueType: requireLiteral2(
      record["valueType"],
      ["null", "boolean", "integer", "string", "enum", "entityRef"],
      `${path}.valueType`
    ),
    nullable: requireBoolean2(record["nullable"], `${path}.nullable`),
    entitySchemaId: record["entitySchemaId"] === null ? null : requireNonEmptyString(record["entitySchemaId"], `${path}.entitySchemaId`),
    defaultValue: parseRuntimeValue(record["defaultValue"], `${path}.defaultValue`)
  };
}
function parseEntityField(value, path) {
  const record = requireRecord2(value, path);
  requireExactKeys2(record, ["id", "key", "valueType", "nullable"], path);
  return {
    id: requireNonEmptyString(record["id"], `${path}.id`),
    key: requireNonEmptyString(record["key"], `${path}.key`),
    valueType: requireLiteral2(
      record["valueType"],
      ["null", "boolean", "integer", "string", "enum", "entityRef"],
      `${path}.valueType`
    ),
    nullable: requireBoolean2(record["nullable"], `${path}.nullable`)
  };
}
function parseEntitySchema(value, path) {
  const record = requireRecord2(value, path);
  requireExactKeys2(record, ["id", "key", "fields"], path);
  return {
    id: requireNonEmptyString(record["id"], `${path}.id`),
    key: requireNonEmptyString(record["key"], `${path}.key`),
    fields: requireArray2(record["fields"], `${path}.fields`).map(
      (field, index) => parseEntityField(field, `${path}.fields[${index}]`)
    )
  };
}
function parseFormField(value, path) {
  const record = requireRecord2(value, path);
  requireExactKeys2(
    record,
    ["id", "key", "valueType", "initialValue", "required", "minInteger"],
    path
  );
  const valueType = requireLiteral2(
    record["valueType"],
    ["string", "integer"],
    `${path}.valueType`
  );
  const initialValue = parseRuntimeValue(record["initialValue"], `${path}.initialValue`);
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
    id: requireNonEmptyString(record["id"], `${path}.id`),
    key: requireNonEmptyString(record["key"], `${path}.key`),
    valueType,
    initialValue: typedInitialValue,
    required: requireBoolean2(record["required"], `${path}.required`),
    minInteger: requireNullableSafeInteger(record["minInteger"], `${path}.minInteger`)
  };
}
function parseForm(value, path) {
  const record = requireRecord2(value, path);
  requireExactKeys2(record, ["id", "key", "fields"], path);
  return {
    id: requireNonEmptyString(record["id"], `${path}.id`),
    key: requireNonEmptyString(record["key"], `${path}.key`),
    fields: requireArray2(record["fields"], `${path}.fields`).map(
      (field, index) => parseFormField(field, `${path}.fields[${index}]`)
    )
  };
}
function parseEntityRefExpression(value, path) {
  const record = requireRecord2(value, path);
  const kind = requireLiteral2(
    record["kind"],
    ["variable", "eventEntityRef"],
    `${path}.kind`
  );
  if (kind === "variable") {
    requireExactKeys2(record, ["kind", "variableId"], path);
    const expression2 = {
      kind,
      variableId: requireNonEmptyString(record["variableId"], `${path}.variableId`)
    };
    return expression2;
  }
  requireExactKeys2(record, ["kind"], path);
  const expression = { kind };
  return expression;
}
function parseValueExpression(value, path, depth = 0) {
  requireDepth(depth, path);
  const record = requireRecord2(value, path);
  const kind = requireLiteral2(
    record["kind"],
    ["literal", "variable", "formField", "eventEntityRef", "entityField"],
    `${path}.kind`
  );
  switch (kind) {
    case "literal":
      requireExactKeys2(record, ["kind", "value"], path);
      return { kind, value: parseRuntimeValue(record["value"], `${path}.value`) };
    case "variable":
      requireExactKeys2(record, ["kind", "variableId"], path);
      return {
        kind,
        variableId: requireNonEmptyString(record["variableId"], `${path}.variableId`)
      };
    case "formField":
      requireExactKeys2(record, ["kind", "formId", "fieldId"], path);
      return {
        kind,
        formId: requireNonEmptyString(record["formId"], `${path}.formId`),
        fieldId: requireNonEmptyString(record["fieldId"], `${path}.fieldId`)
      };
    case "eventEntityRef":
      requireExactKeys2(record, ["kind"], path);
      return { kind };
    case "entityField": {
      requireExactKeys2(record, ["kind", "entityRef", "fieldId", "fallback"], path);
      const expression = {
        kind,
        entityRef: parseEntityRefExpression(record["entityRef"], `${path}.entityRef`),
        fieldId: requireNonEmptyString(record["fieldId"], `${path}.fieldId`),
        fallback: parseRuntimeValue(record["fallback"], `${path}.fallback`)
      };
      return expression;
    }
  }
}
function parsePredicate(value, path, depth = 0) {
  requireDepth(depth, path);
  const record = requireRecord2(value, path);
  const kind = requireLiteral2(
    record["kind"],
    ["all", "roleIs", "formValid", "compare"],
    `${path}.kind`
  );
  switch (kind) {
    case "all":
      requireExactKeys2(record, ["kind", "items"], path);
      return {
        kind,
        items: requireArray2(record["items"], `${path}.items`).map(
          (item, index) => parsePredicate(item, `${path}.items[${index}]`, depth + 1)
        )
      };
    case "roleIs":
      requireExactKeys2(record, ["kind", "roleId"], path);
      return {
        kind,
        roleId: requireNonEmptyString(record["roleId"], `${path}.roleId`)
      };
    case "formValid":
      requireExactKeys2(record, ["kind", "formId"], path);
      return {
        kind,
        formId: requireNonEmptyString(record["formId"], `${path}.formId`)
      };
    case "compare":
      requireExactKeys2(record, ["kind", "operator", "left", "right"], path);
      return {
        kind,
        operator: requireLiteral2(record["operator"], ["eq", "ne"], `${path}.operator`),
        left: parseValueExpression(record["left"], `${path}.left`, depth + 1),
        right: parseValueExpression(record["right"], `${path}.right`, depth + 1)
      };
  }
}
function parseFieldAssignment(value, path) {
  const record = requireRecord2(value, path);
  requireExactKeys2(record, ["fieldId", "value"], path);
  return {
    fieldId: requireNonEmptyString(record["fieldId"], `${path}.fieldId`),
    value: parseValueExpression(record["value"], `${path}.value`)
  };
}
function parseEffect(value, path) {
  const record = requireRecord2(value, path);
  const kind = requireLiteral2(
    record["kind"],
    ["setVariable", "validateForm", "createEntity", "updateEntity", "navigate", "notify"],
    `${path}.kind`
  );
  switch (kind) {
    case "setVariable":
      requireExactKeys2(record, ["kind", "variableId", "value"], path);
      return {
        kind,
        variableId: requireNonEmptyString(record["variableId"], `${path}.variableId`),
        value: parseValueExpression(record["value"], `${path}.value`)
      };
    case "validateForm":
      requireExactKeys2(record, ["kind", "formId"], path);
      return {
        kind,
        formId: requireNonEmptyString(record["formId"], `${path}.formId`)
      };
    case "createEntity":
      requireExactKeys2(record, ["kind", "schemaId", "resultVariableId", "values"], path);
      return {
        kind,
        schemaId: requireNonEmptyString(record["schemaId"], `${path}.schemaId`),
        resultVariableId: requireNonEmptyString(
          record["resultVariableId"],
          `${path}.resultVariableId`
        ),
        values: requireArray2(record["values"], `${path}.values`).map(
          (entry, index) => parseFieldAssignment(entry, `${path}.values[${index}]`)
        )
      };
    case "updateEntity":
      requireExactKeys2(record, ["kind", "schemaId", "entityRef", "updates"], path);
      return {
        kind,
        schemaId: requireNonEmptyString(record["schemaId"], `${path}.schemaId`),
        entityRef: parseEntityRefExpression(record["entityRef"], `${path}.entityRef`),
        updates: requireArray2(record["updates"], `${path}.updates`).map(
          (entry, index) => parseFieldAssignment(entry, `${path}.updates[${index}]`)
        )
      };
    case "navigate":
      requireExactKeys2(record, ["kind", "targetPageId"], path);
      return {
        kind,
        targetPageId: requireNonEmptyString(record["targetPageId"], `${path}.targetPageId`)
      };
    case "notify":
      requireExactKeys2(record, ["kind", "level", "message"], path);
      return {
        kind,
        level: requireLiteral2(
          record["level"],
          ["info", "success", "warning", "error"],
          `${path}.level`
        ),
        message: requireString2(record["message"], `${path}.message`)
      };
  }
}
function parseRule(value, path) {
  const record = requireRecord2(value, path);
  requireExactKeys2(
    record,
    ["id", "key", "enabled", "trigger", "guard", "effects", "guardFalseEffects"],
    path
  );
  const trigger = requireRecord2(record["trigger"], `${path}.trigger`);
  requireExactKeys2(trigger, ["kind", "nodeId", "event"], `${path}.trigger`);
  if (trigger["kind"] !== "nodeEvent") {
    throw new RuntimeInputCodecError(`${path}.trigger.kind must equal nodeEvent`);
  }
  return {
    id: requireNonEmptyString(record["id"], `${path}.id`),
    key: requireNonEmptyString(record["key"], `${path}.key`),
    enabled: requireBoolean2(record["enabled"], `${path}.enabled`),
    trigger: {
      kind: "nodeEvent",
      nodeId: requireNonEmptyString(trigger["nodeId"], `${path}.trigger.nodeId`),
      event: requireLiteral2(
        trigger["event"],
        ["click", "submit", "rowActivated"],
        `${path}.trigger.event`
      )
    },
    guard: record["guard"] === null ? null : parsePredicate(record["guard"], `${path}.guard`),
    effects: requireArray2(record["effects"], `${path}.effects`).map(
      (effect, index) => parseEffect(effect, `${path}.effects[${index}]`)
    ),
    guardFalseEffects: requireArray2(record["guardFalseEffects"], `${path}.guardFalseEffects`).map(
      (effect, index) => parseEffect(effect, `${path}.guardFalseEffects[${index}]`)
    )
  };
}
function parseViewBinding(value, path) {
  const record = requireRecord2(value, path);
  const target = requireLiteral2(
    record["target"],
    ["textContent", "visibility", "tableRows"],
    `${path}.target`
  );
  if (target === "textContent") {
    requireExactKeys2(record, ["id", "nodeId", "target", "value"], path);
    return {
      id: requireNonEmptyString(record["id"], `${path}.id`),
      nodeId: requireNonEmptyString(record["nodeId"], `${path}.nodeId`),
      target,
      value: parseValueExpression(record["value"], `${path}.value`)
    };
  }
  if (target === "visibility") {
    requireExactKeys2(record, ["id", "nodeId", "target", "predicate"], path);
    return {
      id: requireNonEmptyString(record["id"], `${path}.id`),
      nodeId: requireNonEmptyString(record["nodeId"], `${path}.nodeId`),
      target,
      predicate: parsePredicate(record["predicate"], `${path}.predicate`)
    };
  }
  requireExactKeys2(
    record,
    ["id", "nodeId", "target", "schemaId", "sortFieldId", "sortDirection"],
    path
  );
  return {
    id: requireNonEmptyString(record["id"], `${path}.id`),
    nodeId: requireNonEmptyString(record["nodeId"], `${path}.nodeId`),
    target,
    schemaId: requireNonEmptyString(record["schemaId"], `${path}.schemaId`),
    sortFieldId: record["sortFieldId"] === null ? null : requireNonEmptyString(record["sortFieldId"], `${path}.sortFieldId`),
    sortDirection: requireLiteral2(
      record["sortDirection"],
      ["asc", "desc"],
      `${path}.sortDirection`
    )
  };
}
function parseScenario(value, path) {
  const record = requireRecord2(value, path);
  requireExactKeys2(
    record,
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
    id: requireNonEmptyString(record["id"], `${path}.id`),
    key: requireNonEmptyString(record["key"], `${path}.key`),
    actorRoleId: requireNonEmptyString(record["actorRoleId"], `${path}.actorRoleId`),
    startPageId: requireNonEmptyString(record["startPageId"], `${path}.startPageId`),
    initialVariables: requireArray2(record["initialVariables"], `${path}.initialVariables`).map(
      (entry, index) => parseVariableValue(entry, `${path}.initialVariables[${index}]`)
    ),
    entityFixtures: requireArray2(record["entityFixtures"], `${path}.entityFixtures`).map(
      (entry, index) => parseEntitySet(entry, `${path}.entityFixtures[${index}]`)
    ),
    allowSimulatedRoleSwitch: requireBoolean2(
      record["allowSimulatedRoleSwitch"],
      `${path}.allowSimulatedRoleSwitch`
    )
  };
}
function parseFlowLayout(value, path) {
  const record = requireRecord2(value, path);
  requireExactKeys2(record, ["nodes"], path);
  const rawNodes = requireArray2(record["nodes"], `${path}.nodes`);
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
  const record = requireRecord2(value, "runtimeDefinition");
  const hasFlowLayout = Object.hasOwn(record, "flowLayout");
  requireExactKeys2(
    record,
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
  if (record["runtimeSchemaVersion"] !== 1) {
    throw new RuntimeInputCodecError("runtimeDefinition.runtimeSchemaVersion must equal 1");
  }
  return {
    runtimeSchemaVersion: 1,
    pageIds: requireArray2(record["pageIds"], "runtimeDefinition.pageIds").map(
      (pageId, index) => requireNonEmptyString(pageId, `runtimeDefinition.pageIds[${index}]`)
    ),
    roles: requireArray2(record["roles"], "runtimeDefinition.roles").map(
      (role, index) => parseRole(role, `runtimeDefinition.roles[${index}]`)
    ),
    variables: requireArray2(record["variables"], "runtimeDefinition.variables").map(
      (variable, index) => parseVariable(variable, `runtimeDefinition.variables[${index}]`)
    ),
    entitySchemas: requireArray2(record["entitySchemas"], "runtimeDefinition.entitySchemas").map(
      (schema, index) => parseEntitySchema(schema, `runtimeDefinition.entitySchemas[${index}]`)
    ),
    forms: requireArray2(record["forms"], "runtimeDefinition.forms").map(
      (form, index) => parseForm(form, `runtimeDefinition.forms[${index}]`)
    ),
    viewBindings: requireArray2(record["viewBindings"], "runtimeDefinition.viewBindings").map(
      (binding, index) => parseViewBinding(binding, `runtimeDefinition.viewBindings[${index}]`)
    ),
    rules: requireArray2(record["rules"], "runtimeDefinition.rules").map(
      (rule, index) => parseRule(rule, `runtimeDefinition.rules[${index}]`)
    ),
    scenarios: requireArray2(record["scenarios"], "runtimeDefinition.scenarios").map(
      (scenario, index) => parseScenario(scenario, `runtimeDefinition.scenarios[${index}]`)
    ),
    ...hasFlowLayout ? { flowLayout: parseFlowLayout(record["flowLayout"], "runtimeDefinition.flowLayout") } : {}
  };
}
function parseEntityRef(value, path) {
  const parsed = parseRuntimeValue(value, path);
  if (parsed.type !== "entityRef") {
    throw new RuntimeInputCodecError(`${path} must be an entityRef runtime value`);
  }
  return parsed;
}
function parseRuntimeEvent(value, path) {
  const record = requireRecord2(value, path);
  const kind = requireLiteral2(
    record["kind"],
    ["fieldValueCommitted", "nodeActivated", "tableRowActivated", "switchSimulatedRole"],
    `${path}.kind`
  );
  switch (kind) {
    case "fieldValueCommitted":
      requireExactKeys2(record, ["kind", "nodeId", "formId", "fieldId", "value"], path);
      return {
        kind,
        nodeId: requireNonEmptyString(record["nodeId"], `${path}.nodeId`),
        formId: requireNonEmptyString(record["formId"], `${path}.formId`),
        fieldId: requireNonEmptyString(record["fieldId"], `${path}.fieldId`),
        value: parseRuntimeValue(record["value"], `${path}.value`)
      };
    case "nodeActivated":
      requireExactKeys2(record, ["kind", "nodeId", "event"], path);
      return {
        kind,
        nodeId: requireNonEmptyString(record["nodeId"], `${path}.nodeId`),
        event: requireLiteral2(record["event"], ["click", "submit"], `${path}.event`)
      };
    case "tableRowActivated":
      requireExactKeys2(record, ["kind", "nodeId", "entityRef"], path);
      return {
        kind,
        nodeId: requireNonEmptyString(record["nodeId"], `${path}.nodeId`),
        entityRef: parseEntityRef(record["entityRef"], `${path}.entityRef`)
      };
    case "switchSimulatedRole":
      requireExactKeys2(record, ["kind", "roleId"], path);
      return {
        kind,
        roleId: requireNonEmptyString(record["roleId"], `${path}.roleId`)
      };
  }
}
function parseRuntimeEventBatch(value, path = "runtimeEventBatch") {
  const record = requireRecord2(value, path);
  requireExactKeys2(record, ["clientEventId", "expectedSequenceNo", "events"], path);
  return {
    clientEventId: requireNonEmptyString(record["clientEventId"], `${path}.clientEventId`),
    expectedSequenceNo: requireSafeInteger2(
      record["expectedSequenceNo"],
      `${path}.expectedSequenceNo`
    ),
    events: requireArray2(record["events"], `${path}.events`).map(
      (event, index) => parseRuntimeEvent(event, `${path}.events[${index}]`)
    )
  };
}

// src/features/prototype/runtime/runtimeBuildIdentity.ts
var RUNTIME_CORE_SOURCE_HASH = "sha256:2ea354a6f2e11b0511fffb3da8ac434cd5ea4d5a70c77546ec5daf2d19f5097a";

// src/features/prototype/runtime/runtimeWorkerProtocol.ts
var RUNTIME_WORKER_PROTOCOL_VERSION = "prototype-runtime-worker/v1";
var RuntimeWorkerProtocolError = class extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
    this.name = "RuntimeWorkerProtocolError";
  }
  code;
};
function identity() {
  return {
    protocolVersion: RUNTIME_WORKER_PROTOCOL_VERSION,
    runtimeCoreVersion: RUNTIME_CORE_VERSION,
    runtimeCoreSourceHash: RUNTIME_CORE_SOURCE_HASH,
    stateMachineKernelVersion: XSTATE_KERNEL_VERSION
  };
}
function requireExactKeys3(record, expectedKeys, path) {
  const expected = new Set(expectedKeys);
  for (const key of Object.keys(record)) {
    if (!expected.has(key)) {
      throw new RuntimeWorkerProtocolError(
        "runtime_worker_request_invalid",
        `${path} contains unknown field ${key}`
      );
    }
  }
  for (const key of expectedKeys) {
    if (!Object.hasOwn(record, key)) {
      throw new RuntimeWorkerProtocolError(
        "runtime_worker_request_invalid",
        `${path} is missing field ${key}`
      );
    }
  }
}
function requireNonEmptyString2(value, path) {
  if (typeof value !== "string" || value.length === 0) {
    throw new RuntimeWorkerProtocolError(
      "runtime_worker_request_invalid",
      `${path} must be a non-empty string`
    );
  }
  return value;
}
function requireAction(value) {
  if (value === "describe" || value === "initialize" || value === "apply" || value === "replay") {
    return value;
  }
  throw new RuntimeWorkerProtocolError(
    "runtime_worker_action_unsupported",
    "runtime worker action is unsupported"
  );
}
function isRuntimeWorkerAction(value) {
  return value === "describe" || value === "initialize" || value === "apply" || value === "replay";
}
function requireRequestRecord(value) {
  if (!isRecord(value)) {
    throw new RuntimeWorkerProtocolError(
      "runtime_worker_request_invalid",
      "runtime worker request must be an object"
    );
  }
  return value;
}
function parseRuntimeWorkerRequest(value) {
  const record = requireRequestRecord(value);
  if (record["protocolVersion"] !== RUNTIME_WORKER_PROTOCOL_VERSION) {
    throw new RuntimeWorkerProtocolError(
      "runtime_worker_protocol_mismatch",
      `runtime worker protocol must equal ${RUNTIME_WORKER_PROTOCOL_VERSION}`
    );
  }
  const requestId = requireNonEmptyString2(record["requestId"], "request.requestId");
  const action = requireAction(record["action"]);
  if (action === "describe") {
    requireExactKeys3(record, ["protocolVersion", "requestId", "action"], "request");
    return { protocolVersion: RUNTIME_WORKER_PROTOCOL_VERSION, requestId, action };
  }
  if (action === "initialize") {
    requireExactKeys3(
      record,
      ["protocolVersion", "requestId", "action", "definition", "scenarioId", "sessionId"],
      "request"
    );
    return {
      protocolVersion: RUNTIME_WORKER_PROTOCOL_VERSION,
      requestId,
      action,
      definition: parseRuntimeDefinition(record["definition"]),
      scenarioId: requireNonEmptyString2(record["scenarioId"], "request.scenarioId"),
      sessionId: requireNonEmptyString2(record["sessionId"], "request.sessionId")
    };
  }
  if (action === "apply") {
    requireExactKeys3(
      record,
      ["protocolVersion", "requestId", "action", "definition", "stateJson", "batch"],
      "request"
    );
    return {
      protocolVersion: RUNTIME_WORKER_PROTOCOL_VERSION,
      requestId,
      action,
      definition: parseRuntimeDefinition(record["definition"]),
      state: parsePrototypeRuntimeStateJson(
        requireNonEmptyString2(record["stateJson"], "request.stateJson")
      ),
      batch: parseRuntimeEventBatch(record["batch"])
    };
  }
  requireExactKeys3(
    record,
    ["protocolVersion", "requestId", "action", "definition", "stateJson", "batches"],
    "request"
  );
  if (!Array.isArray(record["batches"])) {
    throw new RuntimeWorkerProtocolError(
      "runtime_worker_request_invalid",
      "request.batches must be an array"
    );
  }
  if (record["batches"].length > 200) {
    throw new RuntimeWorkerProtocolError(
      "runtime_worker_replay_tail_limit_exceeded",
      "runtime worker replay tail exceeds 200 event batches"
    );
  }
  return {
    protocolVersion: RUNTIME_WORKER_PROTOCOL_VERSION,
    requestId,
    action,
    definition: parseRuntimeDefinition(record["definition"]),
    state: parsePrototypeRuntimeStateJson(
      requireNonEmptyString2(record["stateJson"], "request.stateJson")
    ),
    batches: record["batches"].map(
      (batch, index) => parseRuntimeEventBatch(batch, `request.batches[${index}]`)
    )
  };
}
function parseRuntimeWorkerRequestJson(input) {
  const parsed = safeJsonParse(input);
  if (parsed === null) {
    throw new RuntimeWorkerProtocolError(
      "runtime_worker_request_invalid_json",
      "runtime worker request JSON is invalid"
    );
  }
  return parseRuntimeWorkerRequest(parsed);
}
function readRuntimeWorkerRequestIdentityJson(input) {
  const parsed = safeJsonParse(input);
  if (!isRecord(parsed)) {
    return { requestId: "unknown", action: "unknown" };
  }
  return {
    requestId: typeof parsed["requestId"] === "string" && parsed["requestId"].length > 0 ? parsed["requestId"] : "unknown",
    action: isRuntimeWorkerAction(parsed["action"]) ? parsed["action"] : "unknown"
  };
}
async function stateResult(state, viewModel) {
  const [stateHash, viewModelHash] = await Promise.all([
    hashRuntimeValue(state),
    hashRuntimeValue(viewModel)
  ]);
  return {
    stateJson: serializePrototypeRuntimeState(state),
    stateHash,
    viewModelJson: canonicalRuntimeJson(viewModel),
    viewModelHash
  };
}
async function apply(definition, state, batch) {
  const transition = await applyRuntimeEventBatch(definition, state, batch);
  const guardReport = {
    outcome: transition.report.outcome,
    matchedRuleIds: transition.report.matchedRuleIds
  };
  const effectReport = { effects: transition.report.effects };
  const [base, eventBatchHash, guardReportHash, effectReportHash] = await Promise.all([
    stateResult(transition.state, transition.viewModel),
    hashRuntimeValue(batch),
    hashRuntimeValue(guardReport),
    hashRuntimeValue(effectReport)
  ]);
  if (base.stateHash !== transition.report.resultStateHash || base.viewModelHash !== transition.report.resultViewModelHash) {
    throw new RuntimeWorkerProtocolError(
      "runtime_worker_transition_hash_mismatch",
      "runtime worker transition result does not match its report hashes"
    );
  }
  return {
    ...base,
    eventsJson: canonicalRuntimeJson(batch.events),
    eventBatchJson: canonicalRuntimeJson(batch),
    eventBatchHash,
    matchedRuleIdsJson: canonicalRuntimeJson(transition.report.matchedRuleIds),
    guardReportJson: canonicalRuntimeJson(guardReport),
    guardReportHash,
    effectReportJson: canonicalRuntimeJson(effectReport),
    effectReportHash,
    report: transition.report
  };
}
async function executeRuntimeWorkerRequest(request) {
  switch (request.action) {
    case "describe":
      return {
        ...identity(),
        requestId: request.requestId,
        action: request.action,
        status: "ok",
        result: identity()
      };
    case "initialize": {
      const state = createInitialRuntimeState(
        request.definition,
        request.scenarioId,
        request.sessionId
      );
      return {
        ...identity(),
        requestId: request.requestId,
        action: request.action,
        status: "ok",
        result: await stateResult(state, deriveRuntimeViewModel(request.definition, state))
      };
    }
    case "apply":
      return {
        ...identity(),
        requestId: request.requestId,
        action: request.action,
        status: "ok",
        result: await apply(request.definition, request.state, request.batch)
      };
    case "replay": {
      const transitions = [];
      let state = request.state;
      for (const batch of request.batches) {
        const transition = await apply(request.definition, state, batch);
        transitions.push(transition);
        state = parsePrototypeRuntimeStateJson(transition.stateJson);
      }
      return {
        ...identity(),
        requestId: request.requestId,
        action: request.action,
        status: "ok",
        result: {
          transitions,
          final: await stateResult(state, deriveRuntimeViewModel(request.definition, state))
        }
      };
    }
  }
}
function runtimeWorkerResponseJson(response) {
  return canonicalRuntimeJson(response);
}
function runtimeWorkerErrorResponse(requestId, action, code, message) {
  return {
    ...identity(),
    requestId,
    action,
    status: "error",
    error: { code, message }
  };
}

// scripts/prototype-runtime-worker.ts
var MAX_REQUEST_BYTES = 4 * 1024 * 1024;
function classifyFailure(error) {
  if (error instanceof RuntimeWorkerProtocolError || error instanceof RuntimeCoreError) {
    return { code: error.code, message: error.message, internal: false };
  }
  if (error instanceof RuntimeInputCodecError) {
    return { code: "runtime_input_invalid", message: error.message, internal: false };
  }
  if (error instanceof RuntimeStateCodecError) {
    return { code: "runtime_state_invalid", message: error.message, internal: false };
  }
  return {
    code: "runtime_worker_internal_error",
    message: "runtime worker failed unexpectedly",
    internal: true
  };
}
async function main() {
  let requestId = "unknown";
  let action = "unknown";
  try {
    process.stdin.setEncoding("utf8");
    let input = "";
    for await (const chunk of process.stdin) {
      if (typeof chunk !== "string") {
        throw new TypeError("runtime worker stdin did not decode as UTF-8 text");
      }
      input += chunk;
      if (Buffer.byteLength(input, "utf8") > MAX_REQUEST_BYTES) {
        throw new RuntimeWorkerProtocolError(
          "runtime_worker_request_too_large",
          "runtime worker request exceeds 4 MiB"
        );
      }
    }
    const requestIdentity = readRuntimeWorkerRequestIdentityJson(input);
    requestId = requestIdentity.requestId;
    action = requestIdentity.action;
    const request = parseRuntimeWorkerRequestJson(input);
    const response = await executeRuntimeWorkerRequest(request);
    process.stdout.write(`${runtimeWorkerResponseJson(response)}
`);
  } catch (error) {
    const failure = classifyFailure(error);
    const response = runtimeWorkerErrorResponse(requestId, action, failure.code, failure.message);
    process.stdout.write(`${runtimeWorkerResponseJson(response)}
`);
    if (failure.internal) {
      const details = error instanceof Error ? error.stack ?? error.message : String(error);
      process.stderr.write(`${details}
`);
      process.exitCode = 1;
    }
  }
}
await main();
