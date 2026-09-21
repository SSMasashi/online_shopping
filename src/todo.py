import json

class TodoList:
    def __init__(self, filepath="todos.json"):
        self.filepath = filepath
        self.todos = []
        self.next_id = 1
        self.load()

    def load(self):
        f = open(self.filepath, "r")
        data = json.load(f)
        self.todos = data["todos"]
        self.next_id = data["next_id"]
        f.close()

    def save(self):
        f = open(self.filepath, "w")
        json.dump({"todos": self.todos, "next_id": self.next_id}, f)
        f.close()

    def add(self, title):
        todo = {"id": self.next_id, "title": title, "done": False}
        self.todos.append(todo)
        self.next_id += 1
        self.save()
        return todo

    def list_all(self):
        return self.todos

    def complete(self, todo_id):
        for todo in self.todos:
            if todo["id"] == todo_id:
                todo["done"] = True
                self.save()
                return todo

    def delete(self, todo_id):
        for i, todo in enumerate(self.todos):
            if todo["id"] == todo_id:
                self.todos.pop(i)
                self.save()
                return True

    def search(self, keyword):
        result = []
        for todo in self.todos:
            if keyword in todo["title"]:
                result.append(todo)
        return result

    def get_stats(self):
        total = len(self.todos)
        done = 0
        for todo in self.todos:
            if todo["done"]:
                done += 1
        return {"total": total, "done": done, "pending": total - done, "rate": done / total}