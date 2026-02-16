# bad_code.py

# ❌ Rule: Dead Code (Unused Import & Variable)
import os 
unused_variable = 100

class SuperMegaManager: 
    # ❌ Rule: God Class (Too many methods, complex)
    
    def __init__(self):
        self.data = []

    # ❌ Rule: Mutable Default Arguments
    def add_item(self, item, cache=[]):
        cache.append(item)
        self.data.append(item)

    # ❌ Rule: Long Method (Too many lines/complexity)
    def process_data_complex(self):
        result = 0
        for i in range(10):
            if i % 2 == 0:
                print("Even")
                for j in range(5):
                    result += j
            else:
                print("Odd")
                if result > 10:
                    result -= 1
        # ... (สมมติว่ายาวมาก) ...
        print("Processing complete")
        print("Step 1")
        print("Step 2")
        print("Step 3")
        print("Step 4")
        print("Step 5")
        print("Step 6")
        print("Step 7")
        print("Step 8")
        print("Step 9")
        print("Step 10")
        print("Step 11")
        print("Step 12")
        print("Step 13")
        print("Step 14")
        print("Step 15")
        return result

    # ❌ Rule: Duplicated Code (Block 1)
    def calculate_tax_thailand(self, price):
        tax_rate = 0.07
        total = price * (1 + tax_rate)
        print(f"Base Price: {price}")
        print(f"Tax: {price * tax_rate}")
        print(f"Total: {total}")
        return total

    # ❌ Rule: Duplicated Code (Block 2 - Similar to above)
    def calculate_tax_similar(self, amount):
        rate = 0.07
        final = amount * (1 + rate)
        print(f"Base Price: {amount}")
        print(f"Tax: {amount * rate}")
        print(f"Total: {final}")
        return final

    # เติม Method ให้เยอะๆ เพื่อกระตุ้น God Class
    def method_3(self): pass
    def method_4(self): pass
    def method_5(self): pass
    def method_6(self): pass
    def method_7(self): pass
    def method_8(self): pass
    def method_9(self): pass
    def method_10(self): pass
    def method_11(self): pass