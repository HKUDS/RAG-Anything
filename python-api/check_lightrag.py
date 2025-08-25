from lightrag import LightRAG
import inspect

sig = inspect.signature(LightRAG.__init__)
print("LightRAG __init__ parameters:")
for param in sig.parameters.values():
    if param.name != 'self':
        print(f"  {param.name}: {param.default if param.default != inspect.Parameter.empty else 'required'}")

# Check if workspace attribute exists
lr = LightRAG(working_dir="./test")
print("\nLightRAG attributes:")
print("  Has 'workspace':", hasattr(lr, 'workspace'))
print("  Has 'working_dir':", hasattr(lr, 'working_dir'))
if hasattr(lr, 'working_dir'):
    print("  working_dir value:", lr.working_dir)