---
name: git_commit
description: >
  Skill para hacer commits semánticos y merge a main de forma segura.
  Se activa cuando el usuario pide "hacer commit", "commitear", "mergear con main"
  o frases similares de gestión de versiones con git.
---

# 🚀 Skill: Git Commit & Merge

Protocolo de commit semántico y merge seguro a `main`.

## Pasos de Ejecución

### 1. Auditoría previa al commit
- Ejecutar `git status --short` para ver archivos modificados.
- Ejecutar `git diff --stat` para entender el alcance de los cambios.
- Identificar archivos temporales, de debug o innecesarios y **eliminarlos** antes de stagear.
  - Patrones a eliminar: `test_*.py`, `debug_*.py`, `*.tmp`, `*.log` fuera de `.gitignore`.
- Verificar que no existan `print()` de depuración en código de producción bajo `src/`.

### 2. Stagear archivos relevantes
- Stagear solo archivos que pertenecen al proyecto (`git add <file>` explícitamente).
- **Nunca** hacer `git add .` sin revisar primero el status.
- Excluir: `uv.lock` a menos que haya cambios de dependencias reales, `.env`, `*.db`.

### 3. Generar mensaje de commit semántico
Seguir la convención [Conventional Commits](https://www.conventionalcommits.org/):

```
<tipo>(<scope opcional>): <descripción corta en imperativo>

- detalle 1
- detalle 2
```

Tipos válidos:
| Tipo | Cuándo usarlo |
|------|--------------|
| `feat` | Nueva funcionalidad |
| `fix` | Corrección de bug |
| `refactor` | Refactoring sin cambio de comportamiento |
| `chore` | Tareas de mantenimiento (deps, config) |
| `docs` | Cambios en documentación |
| `style` | Formato, whitespace (sin cambio de lógica) |
| `perf` | Mejoras de rendimiento |

### 4. Hacer el commit
```bash
git commit -m "<mensaje semántico generado>"
```

### 5. Merge a main (si el usuario lo solicita)
```bash
git checkout main
git merge feat/UI --no-ff -m "merge: feat/UI -> main"
git checkout feat/UI   # volver a la rama de trabajo
```

- Usar `--no-ff` para preservar el historial de la rama.
- Si hay conflictos, reportarlos al usuario antes de continuar.
- Después del merge, **volver a la rama original** de trabajo.

### 6. Reporte final
Mostrar al usuario:
- Hash corto del commit creado.
- Rama actual y destino del merge.
- Archivos incluidos en el commit.
