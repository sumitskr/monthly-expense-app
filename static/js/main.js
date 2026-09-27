document.addEventListener('DOMContentLoaded', function () {
  // Mobile navigation hamburger toggle
  const mobileMenuBtn = document.getElementById('mobileMenuToggle');
  const navLinksMenu = document.getElementById('navLinksMenu');

  if (mobileMenuBtn && navLinksMenu) {
    mobileMenuBtn.addEventListener('click', function () {
      navLinksMenu.classList.toggle('active');
      const icon = mobileMenuBtn.querySelector('i');
      if (icon) {
        if (navLinksMenu.classList.contains('active')) {
          icon.className = 'fa-solid fa-xmark';
        } else {
          icon.className = 'fa-solid fa-bars';
        }
      }
    });
  }

  // Auto-hide alert messages after 6 seconds
  const alerts = document.querySelectorAll('.alert');
  alerts.forEach(function (alert) {
    setTimeout(function () {
      alert.style.opacity = '0';
      alert.style.transition = 'opacity 0.5s ease';
      setTimeout(() => alert.remove(), 500);
    }, 6000);
  });

  // Month select change handler
  const monthSelector = document.getElementById('monthSelector');
  if (monthSelector) {
    monthSelector.addEventListener('change', function () {
      const currentUrl = new URL(window.location.href);
      currentUrl.searchParams.set('month', this.value);
      window.location.href = currentUrl.toString();
    });
  }
});

// Helper function to render Dashboard Chart
function renderCashflowChart(canvasId, salary, emi, savings, expense, cash) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;

  new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: ['Available Cash', 'Fixed EMIs', 'Savings Categories', 'Monthly Expenses'],
      datasets: [{
        data: [
          Math.max(0, cash),
          emi,
          savings,
          expense
        ],
        backgroundColor: [
          '#06b6d4', // Cash Cyan
          '#f43f5e', // EMI Coral
          '#10b981', // Savings Emerald
          '#f59e0b'  // Expense Amber
        ],
        borderWidth: 2,
        borderColor: '#1e293b'
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: 'bottom',
          labels: {
            color: '#94a3b8',
            font: {
              family: 'Plus Jakarta Sans',
              size: 12,
              weight: '600'
            },
            padding: 16
          }
        },
        tooltip: {
          callbacks: {
            label: function (context) {
              const val = context.raw || 0;
              const formatted = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(val);
              return `${context.label}: ${formatted}`;
            }
          }
        }
      },
      cutout: '70%'
    }
  });
}
