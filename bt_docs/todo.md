```
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "Backend",
      "type": "shell",
      "command": "python3 app.py",
      "presentation": {
        "panel": "dedicated",
        "reveal": "always",
        "focus": false
      },
      "problemMatcher": []
    },
    {
      "label": "Frontend",
      "type": "shell",
      "command": "npm run dev",
      "options": {
        "cwd": "${workspaceFolder}/frontend"
      },
      "presentation": {
        "panel": "dedicated",
        "reveal": "always",
        "focus": false
      },
      "problemMatcher": []
    },
    {
      "label": "Logs",
      "type": "shell",
      "command": "tail -f /var/log/my-app.log",
      "presentation": {
        "panel": "dedicated",
        "reveal": "always",
        "focus": false
      },
      "problemMatcher": []
    },
    {
      "label": "Start All",
      "dependsOn": [
        "Backend",
        "Frontend",
        "Logs"
      ],
      "dependsOrder": "parallel",
      "problemMatcher": []
    }
  ]
}
```