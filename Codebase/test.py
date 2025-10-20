import torch

print(torch.backends.mps.is_available())

device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")

# Example tensor operation
x = torch.rand(3, 3).to(device)
y = torch.rand(3, 3).to(device)
z = x + y

print(z)
print(f"Tensor is on device: {z.device}")