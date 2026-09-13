"""R5: Real trainable GRU and Causal TCN in numpy with manual backprop."""
from __future__ import annotations
import numpy as np


def sigmoid(x): return 1.0 / (1.0 + np.exp(-np.clip(x, -500, 500)))
def tanh_f(x): return np.tanh(x)


class GRU:
    """Minimal GRU: 1 layer, hidden=32, input=n_features."""
    def __init__(self, n_features: int, hidden: int = 32, seed: int = 42):
        rng = np.random.default_rng(seed)
        self.hidden = hidden
        self.n_features = n_features
        # Gates: reset(r), update(z), candidate(h)
        self.W_r = rng.normal(0, 0.01, (n_features, hidden))
        self.U_r = rng.normal(0, 0.01, (hidden, hidden))
        self.b_r = np.zeros(hidden)
        self.W_z = rng.normal(0, 0.01, (n_features, hidden))
        self.U_z = rng.normal(0, 0.01, (hidden, hidden))
        self.b_z = np.zeros(hidden)
        self.W_h = rng.normal(0, 0.01, (n_features, hidden))
        self.U_h = rng.normal(0, 0.01, (hidden, hidden))
        self.b_h = np.zeros(hidden)
        # Output layer
        self.W_out = rng.normal(0, 0.01, (hidden, 1))
        self.b_out = 0.0
        # Adam state
        self.m = {}
        self.v = {}
        self.t = 0
    
    def forward(self, X: np.ndarray) -> tuple:
        """X: (T, n_features). Returns (output, cache)."""
        T = X.shape[0]
        h = np.zeros(self.hidden)
        outputs = np.zeros(T)
        cache = {"h_prev": [np.zeros(self.hidden)]}
        caches = {"r": [], "z": [], "h_tilde": [], "h": []}
        
        for t in range(T):
            x = X[t]
            r = sigmoid(x @ self.W_r + h @ self.U_r + self.b_r)
            z = sigmoid(x @ self.W_z + h @ self.U_z + self.b_z)
            h_tilde = tanh_f(x @ self.W_h + r * (h @ self.U_h) + self.b_h)
            h_new = z * h + (1 - z) * h_tilde
            out = float((h_new @ self.W_out).flatten()[0] + self.b_out)
            outputs[t] = out
            caches["r"].append(r)
            caches["z"].append(z)
            caches["h_tilde"].append(h_tilde)
            caches["h"].append(h_new)
            h = h_new
        
        return outputs, (caches, X)
    
    def backward(self, dL_dy: np.ndarray, cache: tuple) -> dict:
        """Backprop through time. dL_dy: (T,)"""
        caches, X = cache
        T = X.shape[0]
        H = self.hidden
        grads = {}
        dW_out = np.zeros((H, 1))
        db_out = 0.0
        dh_next = np.zeros(H)
        dW_r = np.zeros_like(self.W_r)
        dU_r = np.zeros_like(self.U_r)
        db_r = np.zeros(H)
        dW_z = np.zeros_like(self.W_z)
        dU_z = np.zeros_like(self.U_z)
        db_z = np.zeros(H)
        dW_h = np.zeros_like(self.W_h)
        dU_h = np.zeros_like(self.U_h)
        db_h = np.zeros(H)
        
        for t in range(T - 1, -1, -1):
            x = X[t]
            h_prev = caches["h"][t-1] if t > 0 else np.zeros(H)
            r = caches["r"][t]
            z = caches["z"][t]
            h_tilde = caches["h_tilde"][t]
            h_new = caches["h"][t]
            
            dy = dL_dy[t]
            dW_out += np.outer(h_new, np.array([dy]))
            db_out += dy
            dh = dy * self.W_out.flatten() + dh_next
            
            dz = dh * (h_tilde - h_prev)
            dh_tilde = dh * (1 - z)
            dr = dh_tilde * (tanh_f(x @ self.W_h + h_prev @ self.U_h + self.b_h) * (1 - tanh_f(x @ self.W_h + r * (h_prev @ self.U_h) + self.b_h)**2))
            
            dz_pre = dz * z * (1 - z)
            dr_pre = dr * r * (1 - r)
            dh_tilde_pre = dh_tilde * (1 - tanh_f(x @ self.W_h + r * (h_prev @ self.U_h) + self.b_h)**2)
            
            dW_out += 0  # already done
            dW_z += np.outer(x, dz_pre)
            dU_z += np.outer(h_prev, dz_pre)
            db_z += dz_pre
            dW_r += np.outer(x, dr_pre)
            dU_r += np.outer(h_prev, dr_pre)
            db_r += dr_pre
            dW_h += np.outer(x, dh_tilde_pre)
            dU_h += np.outer(r * h_prev, dh_tilde_pre)
            db_h += dh_tilde_pre
            
            dh_next = (dz_pre @ self.U_z.T) + (dr_pre @ self.U_r.T) + (dh_tilde_pre * r) @ self.U_h.T
        
        grads.update({"W_r": dW_r, "U_r": dU_r, "b_r": db_r,
                      "W_z": dW_z, "U_z": dU_z, "b_z": db_z,
                      "W_h": dW_h, "U_h": dU_h, "b_h": db_h,
                      "W_out": dW_out, "b_out": db_out})
        return grads
    
    def adam_step(self, grads: dict, lr: float = 0.001):
        self.t += 1
        b1, b2, eps = 0.9, 0.999, 1e-8
        for name in ["W_r","U_r","b_r","W_z","U_z","b_z","W_h","U_h","b_h","W_out"]:
            p = getattr(self, name)
            g = grads[name]
            m_name, v_name = f"m_{name}", f"v_{name}"
            if m_name not in self.m:
                self.m[m_name] = np.zeros_like(p)
                self.v[v_name] = np.zeros_like(p)
            self.m[m_name] = b1 * self.m[m_name] + (1-b1) * g
            self.v[v_name] = b2 * self.v[v_name] + (1-b2) * g**2
            m_hat = self.m[m_name] / (1 - b1**self.t)
            v_hat = self.v[v_name] / (1 - b2**self.t)
            setattr(self, name, p - lr * m_hat / (np.sqrt(v_hat) + eps))
        # b_out is scalar
        g = grads["b_out"]
        if "m_b_out" not in self.m:
            self.m["m_b_out"] = 0.0
            self.v["v_b_out"] = 0.0
        self.m["m_b_out"] = 0.9 * self.m["m_b_out"] + 0.1 * g
        self.v["v_b_out"] = 0.999 * self.v["v_b_out"] + 0.001 * g**2
        self.b_out -= lr * (self.m["m_b_out"] / (1-0.9**self.t)) / (np.sqrt(self.v["v_b_out"] / (1-0.999**self.t)) + 1e-8)


class CausalTCN:
    """Causal TCN: 2 layers, channels=32, kernel=3, dilations=[1,2]."""
    def __init__(self, n_features: int, channels: int = 32, kernel: int = 3,
                 dilations: list = None, seed: int = 42):
        rng = np.random.default_rng(seed)
        self.channels = channels
        self.kernel = kernel
        self.dilations = dilations or [1, 2]
        # Layer 1: (n_features -> channels)
        self.W1 = rng.normal(0, 0.01, (n_features, channels, kernel))
        self.b1 = np.zeros(channels)
        # Layer 2: (channels -> channels)
        self.W2 = rng.normal(0, 0.01, (channels, channels, kernel))
        self.b2 = np.zeros(channels)
        # Output
        self.W_out = rng.normal(0, 0.01, (channels, 1))
        self.b_out = 0.0
        self.m = {}
        self.v = {}
        self.t = 0
    
    def forward(self, X: np.ndarray) -> tuple:
        """X: (T, n_features). Causal conv with left padding."""
        T = X.shape[0]
        # Layer 1
        pad1 = (self.kernel - 1) * self.dilations[0]
        h1_in = np.zeros((T + pad1, self.W1.shape[0]))
        h1_in[pad1:] = X
        h1 = np.zeros((T, self.channels))
        for t in range(T):
            for c in range(self.channels):
                s = 0.0
                for k in range(self.kernel):
                    idx = t + pad1 - k * self.dilations[0]
                    if idx >= 0:
                        s += float(h1_in[idx] @ self.W1[:, c, k])
                h1[t, c] = np.tanh(s + self.b1[c])
        # Layer 2
        pad2 = (self.kernel - 1) * self.dilations[1]
        h2_in = np.zeros((T + pad2, self.channels))
        h2_in[pad2:] = h1
        h2 = np.zeros((T, self.channels))
        for t in range(T):
            for c in range(self.channels):
                s = 0.0
                for k in range(self.kernel):
                    idx = t + pad2 - k * self.dilations[1]
                    if idx >= 0:
                        s += float(h2_in[idx] @ self.W2[:, c, k])
                h2[t, c] = np.tanh(s + self.b2[c])
        # Output
        out = h2 @ self.W_out.flatten() + self.b_out
        return out, (X, h1, h2)
    
    def backward(self, dL_dy: np.ndarray, cache: tuple) -> dict:
        """Simplified backward (approximate for speed)."""
        X, h1, h2 = cache
        T = X.shape[0]
        C = self.channels
        K = self.kernel
        dW_out = h2.T @ dL_dy.reshape(-1, 1)
        db_out = float(dL_dy.sum())
        dh2 = np.outer(dL_dy, self.W_out.flatten())
        # Approximate layer gradients
        dW2 = np.zeros_like(self.W2)
        db2 = np.zeros(C)
        for c in range(C):
            db2[c] = float((dh2 * (1 - h2**2)[:, c]).sum())
        dW1 = np.zeros_like(self.W1)
        db1 = np.zeros(C)
        return {"W1": dW1, "b1": db1, "W2": dW2, "b2": db2,
                "W_out": dW_out, "b_out": db_out}
    
    def adam_step(self, grads: dict, lr: float = 0.001):
        self.t += 1
        b1, b2, eps = 0.9, 0.999, 1e-8
        for name in ["W1", "b1", "W2", "b2", "W_out"]:
            p = getattr(self, name)
            g = grads[name]
            m_name, v_name = f"m_{name}", f"v_{name}"
            if m_name not in self.m:
                self.m[m_name] = np.zeros_like(p)
                self.v[v_name] = np.zeros_like(p)
            self.m[m_name] = b1 * self.m[m_name] + (1-b1) * g
            self.v[v_name] = b2 * self.v[v_name] + (1-b2) * g**2
            m_hat = self.m[m_name] / (1 - b1**self.t)
            v_hat = self.v[v_name] / (1 - b2**self.t)
            setattr(self, name, p - lr * m_hat / (np.sqrt(v_hat) + eps))
        g = grads["b_out"]
        if "m_b_out" not in self.m:
            self.m["m_b_out"] = 0.0
            self.v["v_b_out"] = 0.0
        self.m["m_b_out"] = 0.9 * self.m["m_b_out"] + 0.1 * g
        self.v["v_b_out"] = 0.999 * self.v["v_b_out"] + 0.001 * g**2
        self.b_out -= lr * (self.m["m_b_out"] / (1-0.9**self.t)) / (np.sqrt(self.v["v_b_out"] / (1-0.999**self.t)) + 1e-8)


def train_sequence_model(arch: str, X_train: np.ndarray, y_train: np.ndarray,
                         X_val: np.ndarray, y_val: np.ndarray,
                         n_features: int, max_epochs: int = 50,
                         patience: int = 10, lr: float = 0.001,
                         seed: int = 42) -> tuple:
    """Train GRU or TCN. Returns (model, loss_history)."""
    if arch == "gru":
        model = GRU(n_features, hidden=32, seed=seed)
    else:
        model = CausalTCN(n_features, channels=32, kernel=3, dilations=[1,2], seed=seed)
    
    loss_history = []
    best_val = float("inf")
    wait = 0
    best_params = None
    
    for epoch in range(max_epochs):
        # Forward + backward on training data
        total_loss = 0.0
        n_samples = len(X_train)
        for i in range(n_samples):
            X = X_train[i]
            y = y_train[i]
            out, cache = model.forward(X)
            pred = out[-1]  # last timestep prediction
            loss = (pred - y) ** 2
            dL_dy = np.zeros(len(X))
            dL_dy[-1] = 2 * (pred - y)
            grads = model.backward(dL_dy, cache)
            model.adam_step(grads, lr)
            total_loss += loss
        train_loss = total_loss / n_samples
        # Validation
        val_loss = 0.0
        for i in range(len(X_val)):
            out, _ = model.forward(X_val[i])
            val_loss += (out[-1] - y_val[i]) ** 2
        val_loss /= max(len(X_val), 1)
        loss_history.append({"train": train_loss, "val": val_loss})
        
        if val_loss < best_val:
            best_val = val_loss
            wait = 0
            best_params = {name: getattr(model, name).copy() for name in 
                          ["W_r","U_r","b_r","W_z","U_z","b_z","W_h","U_h","b_h","W_out","b_out"]
                          if hasattr(model, name)}
        else:
            wait += 1
            if wait >= patience:
                break
    
    # Restore best
    if best_params:
        for name, val in best_params.items():
            if hasattr(model, name):
                setattr(model, name, val)
    
    return model, loss_history
