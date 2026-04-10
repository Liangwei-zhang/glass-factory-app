import bcrypt from 'bcryptjs';
import jwt from 'jsonwebtoken';

import { JWT_EXPIRES_IN, JWT_SECRET } from './config.js';
import { STAGE_LABELS } from './constants.js';
import { getUserByEmail, getUserById } from './persistence/index.js';

function sanitizeUser(row) {
  if (!row) {
    return null;
  }

  return {
    id: row.id,
    name: row.name,
    email: row.email,
    role: row.role,
    stage: row.stage,
    stageLabel: row.stage ? STAGE_LABELS[row.stage] ?? row.stage : null,
  };
}

export async function authenticateUser(email, password) {
  const user = await getUserByEmail(email.trim().toLowerCase());

  if (!user || !bcrypt.compareSync(password, user.password_hash)) {
    return null;
  }

  return sanitizeUser(user);
}

export function issueToken(user) {
  return jwt.sign({ sub: user.id }, JWT_SECRET, { expiresIn: JWT_EXPIRES_IN });
}

export function requireAuth(allowedRoles = []) {
  return async (req, res, next) => {
    const header = req.headers.authorization ?? '';
    const token = header.startsWith('Bearer ') ? header.slice(7) : null;

    if (!token) {
      return res.status(401).json({ error: '缺少登录令牌。' });
    }

    try {
      const payload = jwt.verify(token, JWT_SECRET);
      const user = sanitizeUser(await getUserById(payload.sub));

      if (!user) {
        return res.status(401).json({ error: '登录已失效，请重新登录。' });
      }

      if (allowedRoles.length && !allowedRoles.includes(user.role)) {
        return res.status(403).json({ error: '当前角色无权执行此操作。' });
      }

      req.user = user;
      return next();
    } catch {
      return res.status(401).json({ error: '登录已失效，请重新登录。' });
    }
  };
}